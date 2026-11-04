from __future__ import annotations

import csv
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

LEDGER_FIELDS = [
    "session_date",
    "family",
    "direction",
    "rescue_timestamp",
    "rescue_price",
    "reentry_timestamp",
    "reentry_price",
    "terminal_timestamp",
    "terminal_price",
    "r1_exit_timestamp",
    "r1_exit_price",
    "r2_exit_timestamp",
    "r2_exit_price",
    "notes",
]


def _dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _dpoints(direction: str, a: float, b: float) -> float:
    return b - a if direction == "BULLISH" else a - b


@dataclass
class ForwardCase:
    session_date: str
    family: str
    direction: str
    rescue_timestamp: str
    rescue_price: float
    reentry_timestamp: str
    reentry_price: float

    terminal_timestamp: str = ""
    terminal_price: Optional[float] = None

    r1_exit_timestamp: str = ""
    r1_exit_price: Optional[float] = None

    r2_exit_timestamp: str = ""
    r2_exit_price: Optional[float] = None

    notes: str = ""

    # research-only running state; not persisted in ledger
    r1_armed: bool = False
    r2_armed: bool = False
    running_mfe: float = 0.0
    finished: bool = False


class MidpointV621ForwardOOSCollector:
    """
    Observation-only shadow collector for V62 frozen re-entry candidates.

    It NEVER sends orders and NEVER mutates B/E/CAP20/re-entry decisions.

    Feed:
      - audit events emitted by the live coordinator
      - every completed 1m underlying candle

    R1:
      after frozen re-entry, once favorable intrabar excursion >= +20,
      first completed 1m close back to <= +10 exits the research leg.

    R2:
      after frozen re-entry, once running favorable excursion >= +20,
      first completed 1m close <= running MFE - 20 exits the research leg.
    """

    CAP20_EVENTS = {"CAP20_RESCUE_TRIGGERED", "CAP20_SHADOW_EXIT"}
    REENTRY_EVENTS = {
        "POST_CAP20_REENTRY_TRIGGERED",
        "POST_RESCUE_REENTRY_TRIGGERED",
        "REENTRY_COUNT_1",
    }

    def __init__(self, ledger_path: Path):
        self.ledger_path = Path(ledger_path)
        self._pending_rescue: dict[str, dict] = {}
        self._active: dict[str, ForwardCase] = {}
        self._ensure_ledger()

    def _ensure_ledger(self):
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.ledger_path.exists():
            with self.ledger_path.open("w", newline="") as fh:
                csv.DictWriter(fh, fieldnames=LEDGER_FIELDS).writeheader()

    @staticmethod
    def _key(direction: str, family: str) -> str:
        return f"{family}:{direction}"

    @staticmethod
    def _price_from_event(event: dict) -> Optional[float]:
        value = event.get("underlying_price")
        return None if value is None else float(value)

    def on_audit_event(self, event: dict) -> None:
        et = event.get("event_type")
        direction = event.get("direction")
        family = event.get("family") or (event.get("evidence") or {}).get("family_selected")
        ts = event.get("event_timestamp")

        if not direction or not ts:
            return

        # CAP20 event may not carry family. Preserve by direction if necessary.
        if et in self.CAP20_EVENTS:
            px = self._price_from_event(event)
            if px is None:
                return
            rescue = {
                "timestamp": ts,
                "price": px,
                "direction": direction,
                "family": family or "",
            }
            self._pending_rescue[direction] = rescue
            return

        if et in self.REENTRY_EVENTS:
            px = self._price_from_event(event)
            if px is None:
                return
            rescue = self._pending_rescue.get(direction)
            if not rescue:
                return

            fam = family or rescue.get("family") or ""
            if not fam:
                # family should normally exist on re-entry; fail closed if absent
                return

            case = ForwardCase(
                session_date=_dt(ts).date().isoformat(),
                family=fam,
                direction=direction,
                rescue_timestamp=rescue["timestamp"],
                rescue_price=float(rescue["price"]),
                reentry_timestamp=ts,
                reentry_price=px,
                notes="V62.1_FORWARD_OOS_AUTO",
            )
            self._active[self._key(direction, fam)] = case
            return

        if et == "STRUCTURAL_TERMINAL":
            px = self._price_from_event(event)
            if px is None:
                return
            # terminal belongs to whichever active research case shares direction;
            # normally only one active midpoint reference exists.
            matches = [
                (k, c) for k, c in self._active.items()
                if c.direction == direction and not c.finished
            ]
            if len(matches) != 1:
                return
            key, case = matches[0]
            case.terminal_timestamp = ts
            case.terminal_price = px
            case.finished = True
            self._append_completed(case)
            del self._active[key]
            self._pending_rescue.pop(direction, None)

    def on_completed_underlying_candle(
        self,
        *,
        timestamp: str,
        high: float,
        low: float,
        close: float,
    ) -> None:
        ts = _dt(timestamp)

        for case in list(self._active.values()):
            if case.finished:
                continue
            if ts <= _dt(case.reentry_timestamp):
                continue

            if case.direction == "BULLISH":
                favorable = float(high) - case.reentry_price
                close_move = float(close) - case.reentry_price
            else:
                favorable = case.reentry_price - float(low)
                close_move = case.reentry_price - float(close)

            case.running_mfe = max(case.running_mfe, favorable)

            # R1: +20 proof -> protect +10 on completed close
            if case.r1_exit_price is None:
                if case.running_mfe >= 20.0:
                    case.r1_armed = True
                if case.r1_armed and close_move <= 10.0:
                    case.r1_exit_timestamp = timestamp
                    case.r1_exit_price = float(close)

            # R2: +20 proof -> 20-point trail from running MFE
            if case.r2_exit_price is None:
                if case.running_mfe >= 20.0:
                    case.r2_armed = True
                if case.r2_armed and close_move <= case.running_mfe - 20.0:
                    case.r2_exit_timestamp = timestamp
                    case.r2_exit_price = float(close)

    def _append_completed(self, case: ForwardCase) -> None:
        row = {k: getattr(case, k) for k in LEDGER_FIELDS}
        with self.ledger_path.open("a", newline="") as fh:
            csv.DictWriter(fh, fieldnames=LEDGER_FIELDS).writerow(row)

    def active_snapshot(self) -> list[dict]:
        return [asdict(c) for c in self._active.values()]
