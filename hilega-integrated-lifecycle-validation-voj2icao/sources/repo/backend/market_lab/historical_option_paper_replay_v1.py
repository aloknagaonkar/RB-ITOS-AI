from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .domain import IST
from .historical_positioning_adapter_v1 import (
    PositioningRow,
    PositioningSession,
    choose_positioning_session,
    timestamp_groups,
)
from .historical_paper_replay_date_v1 import replay_date


HISTORICAL_FILL_MODEL = "CHECKPOINT_CLOSE_PROXY_V1"
MAX_OPEN_POSITIONS = 4
HARD_STOP_PCT = -5.0
BREAKEVEN_ARM_PCT = 5.0
TRAIL_ARM_PCT = 10.0
TRAIL_DISTANCE_PCT = 3.0


class HistoricalPaperReplayError(RuntimeError):
    pass


@dataclass
class HistoricalPaperPosition:
    position_id: str
    session_date: str
    direction: str
    option_type: str
    strike: float
    instrument_key: str
    opened_at: str
    entry_price: float
    quantity: int = 1
    status: str = "OPEN"
    highest_price: float | None = None
    breakeven_armed: bool = False
    trailing_armed: bool = False
    active_stop_price: float | None = None
    closed_at: str | None = None
    exit_price: float | None = None
    exit_reason: str | None = None

    def __post_init__(self):
        if self.highest_price is None:
            self.highest_price = self.entry_price
        if self.active_stop_price is None:
            self.active_stop_price = self.entry_price * 0.95

    @property
    def pnl_pct(self) -> float | None:
        if self.exit_price is None:
            return None
        return ((self.exit_price / self.entry_price) - 1.0) * 100.0


@dataclass(frozen=True)
class HistoricalPaperEvent:
    timestamp: str
    event_type: str
    status: str
    reason_code: str | None = None
    position_id: str | None = None
    data: dict = field(default_factory=dict)


@dataclass
class HistoricalPaperReplayResult:
    session_date: str
    fill_model: str
    max_open_positions: int
    positions: list[HistoricalPaperPosition] = field(default_factory=list)
    events: list[HistoricalPaperEvent] = field(default_factory=list)
    p2_candidates: int = 0
    entries: int = 0
    capacity_rejects: int = 0
    exact_atm_rejects: int = 0
    quote_rejects: int = 0

    def summary(self) -> dict:
        closed = [p for p in self.positions if p.status == "CLOSED"]
        winners = [p for p in closed if (p.pnl_pct or 0) > 0]
        losers = [p for p in closed if (p.pnl_pct or 0) < 0]
        return {
            "session_date": self.session_date,
            "fill_model": self.fill_model,
            "p2_candidates": self.p2_candidates,
            "entries": self.entries,
            "closed_positions": len(closed),
            "open_at_end": sum(1 for p in self.positions if p.status == "OPEN"),
            "capacity_rejects": self.capacity_rejects,
            "exact_atm_rejects": self.exact_atm_rejects,
            "quote_rejects": self.quote_rejects,
            "winners": len(winners),
            "losers": len(losers),
            "aggregate_pnl_pct": sum((p.pnl_pct or 0.0) for p in closed),
        }


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(IST)


def _premium_for(row: PositioningRow, option_type: str) -> tuple[str, float | None]:
    if option_type == "CE":
        return row.ce_instrument_key, row.ce_close
    if option_type == "PE":
        return row.pe_instrument_key, row.pe_close
    raise HistoricalPaperReplayError(f"Unsupported option type: {option_type}")


def _exact_atm_row(rows: Iterable[PositioningRow], atm: float) -> PositioningRow | None:
    for row in rows:
        if float(row.strike) == float(atm):
            return row
    return None


def _update_position(
    position: HistoricalPaperPosition,
    *,
    timestamp: str,
    price: float,
) -> HistoricalPaperEvent | None:
    if position.status != "OPEN":
        return None

    if price <= 0:
        return HistoricalPaperEvent(
            timestamp=timestamp,
            event_type="POSITION_MARK_REJECTED",
            status="FAIL",
            reason_code="INVALID_PREMIUM_CLOSE",
            position_id=position.position_id,
            data={"price": price},
        )

    if price > (position.highest_price or position.entry_price):
        position.highest_price = price

    gain_pct = ((price / position.entry_price) - 1.0) * 100.0

    if not position.breakeven_armed and gain_pct >= BREAKEVEN_ARM_PCT:
        position.breakeven_armed = True
        position.active_stop_price = max(
            position.active_stop_price or 0.0,
            position.entry_price,
        )

    if not position.trailing_armed and gain_pct >= TRAIL_ARM_PCT:
        position.trailing_armed = True

    if position.trailing_armed:
        trail_stop = (position.highest_price or price) * (1.0 - TRAIL_DISTANCE_PCT / 100.0)
        position.active_stop_price = max(
            position.active_stop_price or 0.0,
            trail_stop,
        )

    if price <= (position.active_stop_price or 0.0):
        if position.trailing_armed:
            reason = "TRAIL_STOP"
        elif position.breakeven_armed:
            reason = "BREAKEVEN_STOP"
        else:
            reason = "HARD_STOP"

        position.status = "CLOSED"
        position.closed_at = timestamp
        position.exit_price = price
        position.exit_reason = reason

        return HistoricalPaperEvent(
            timestamp=timestamp,
            event_type="POSITION_CLOSED",
            status="PASS",
            reason_code=reason,
            position_id=position.position_id,
            data={
                "exit_price": price,
                "pnl_pct": position.pnl_pct,
                "active_stop_price": position.active_stop_price,
            },
        )

    return HistoricalPaperEvent(
        timestamp=timestamp,
        event_type="POSITION_MARKED",
        status="PASS",
        position_id=position.position_id,
        data={
            "price": price,
            "gain_pct": gain_pct,
            "highest_price": position.highest_price,
            "breakeven_armed": position.breakeven_armed,
            "trailing_armed": position.trailing_armed,
            "active_stop_price": position.active_stop_price,
        },
    )


def replay_historical_paper_date(
    session_date: str,
    *,
    data_root: str | Path = "data",
    futures_csv: str | Path = "data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv",
) -> HistoricalPaperReplayResult:
    signal_replay = replay_date(
        session_date,
        data_root=data_root,
        futures_csv=futures_csv,
    )
    positioning = choose_positioning_session(
        session_date,
        data_root=data_root,
    )
    groups = timestamp_groups(positioning)

    result = HistoricalPaperReplayResult(
        session_date=session_date,
        fill_model=HISTORICAL_FILL_MODEL,
        max_open_positions=MAX_OPEN_POSITIONS,
    )

    p2_events = [
        event for event in signal_replay.events
        if event.event_type == "P2_CONFIRMED_RUNTIME"
    ]
    p2_by_ts = {_parse_ts(event.timestamp): event for event in p2_events}

    position_seq = 0

    for ts, rows in groups.items():
        # First mark existing positions at this checkpoint.
        for position in [p for p in result.positions if p.status == "OPEN"]:
            row = next(
                (
                    item for item in rows
                    if float(item.strike) == float(position.strike)
                ),
                None,
            )
            if row is None:
                result.events.append(
                    HistoricalPaperEvent(
                        timestamp=ts.isoformat(),
                        event_type="POSITION_MARK_REJECTED",
                        status="FAIL",
                        reason_code="OPTION_STRIKE_NOT_AVAILABLE",
                        position_id=position.position_id,
                    )
                )
                continue

            _, premium = _premium_for(row, position.option_type)
            if premium is None or premium <= 0:
                result.events.append(
                    HistoricalPaperEvent(
                        timestamp=ts.isoformat(),
                        event_type="POSITION_MARK_REJECTED",
                        status="FAIL",
                        reason_code="OPTION_PREMIUM_UNAVAILABLE",
                        position_id=position.position_id,
                    )
                )
                continue

            event = _update_position(
                position,
                timestamp=ts.isoformat(),
                price=float(premium),
            )
            if event is not None:
                result.events.append(event)

        p2_event = p2_by_ts.get(ts)
        if p2_event is None:
            continue

        result.p2_candidates += 1

        open_count = sum(1 for p in result.positions if p.status == "OPEN")
        if open_count >= MAX_OPEN_POSITIONS:
            result.capacity_rejects += 1
            result.events.append(
                HistoricalPaperEvent(
                    timestamp=ts.isoformat(),
                    event_type="PAPER_ENTRY_REJECTED",
                    status="FAIL",
                    reason_code="MAX_OPEN_POSITIONS",
                    data={"open_positions": open_count},
                )
            )
            continue

        direction = p2_event.direction
        option_type = "CE" if direction == "BULLISH" else "PE"

        oi = p2_event.data.get("oi") or {}
        atm = oi.get("atm")
        if atm is None:
            result.exact_atm_rejects += 1
            result.events.append(
                HistoricalPaperEvent(
                    timestamp=ts.isoformat(),
                    event_type="PAPER_ENTRY_REJECTED",
                    status="FAIL",
                    reason_code="ATM_UNAVAILABLE",
                )
            )
            continue

        row = _exact_atm_row(rows, float(atm))
        if row is None:
            result.exact_atm_rejects += 1
            result.events.append(
                HistoricalPaperEvent(
                    timestamp=ts.isoformat(),
                    event_type="PAPER_ENTRY_REJECTED",
                    status="FAIL",
                    reason_code="EXACT_ATM_NOT_AVAILABLE",
                    data={"atm": atm, "option_type": option_type},
                )
            )
            continue

        instrument_key, premium = _premium_for(row, option_type)
        if premium is None or premium <= 0:
            result.quote_rejects += 1
            result.events.append(
                HistoricalPaperEvent(
                    timestamp=ts.isoformat(),
                    event_type="PAPER_ENTRY_REJECTED",
                    status="FAIL",
                    reason_code="OPTION_PREMIUM_UNAVAILABLE",
                    data={
                        "atm": atm,
                        "option_type": option_type,
                        "instrument_key": instrument_key,
                    },
                )
            )
            continue

        position_seq += 1
        position = HistoricalPaperPosition(
            position_id=f"{session_date}-{position_seq:03d}",
            session_date=session_date,
            direction=direction,
            option_type=option_type,
            strike=float(atm),
            instrument_key=instrument_key,
            opened_at=ts.isoformat(),
            entry_price=float(premium),
        )
        result.positions.append(position)
        result.entries += 1
        result.events.append(
            HistoricalPaperEvent(
                timestamp=ts.isoformat(),
                event_type="PAPER_POSITION_OPENED",
                status="PASS",
                position_id=position.position_id,
                data={
                    "direction": direction,
                    "option_type": option_type,
                    "strike": float(atm),
                    "instrument_key": instrument_key,
                    "entry_price": float(premium),
                    "fill_model": HISTORICAL_FILL_MODEL,
                    "hard_stop_pct": HARD_STOP_PCT,
                    "breakeven_arm_pct": BREAKEVEN_ARM_PCT,
                    "trail_arm_pct": TRAIL_ARM_PCT,
                    "trail_distance_pct": TRAIL_DISTANCE_PCT,
                },
            )
        )

    return result
