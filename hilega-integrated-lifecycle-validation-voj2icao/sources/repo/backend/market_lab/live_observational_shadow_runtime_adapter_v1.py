from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from .live_observational_shadow_v1 import AuditStore, ShadowEngine, reconstruct_states

MODEL = "LIVE_OBSERVATIONAL_SHADOW_RUNTIME_ADAPTER_V1_1"

Direction = Literal["BULLISH", "BEARISH"]
All3State = Literal["BULLISH_ALL_3", "BEARISH_ALL_3", "MIXED", "INCOMPLETE"]

SUPPORTIVE_FUTURES = {
    "BULLISH": {"LONG_BUILDUP", "SHORT_COVERING"},
    "BEARISH": {"SHORT_BUILDUP", "LONG_UNWINDING"},
}


@dataclass(frozen=True)
class CompletedFiveMinuteCheckpoint:
    session_date: str
    timestamp: datetime
    all3_state: All3State
    spot: float
    futures_oi_state: str | None = None


@dataclass(frozen=True)
class ExactOptionResolution:
    timestamp: datetime
    atm_strike: float
    option_instrument_key: str


@dataclass(frozen=True)
class ExactNextMinuteOpen:
    timestamp: datetime
    price: float


@dataclass(frozen=True)
class CompletedOptionMinute:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


class LiveShadowRuntimeAdapterV1:
    """Production-safe bridge into LIVE_OBSERVATIONAL_SHADOW_V1."""

    def __init__(self, events_jsonl: str | Path):
        self.store = AuditStore(events_jsonl)
        self.shadow = ShadowEngine(self.store)

    @staticmethod
    def observation_id(
        session_date: str,
        direction: Direction,
        candle1_timestamp: datetime,
    ) -> str:
        stamp = candle1_timestamp.strftime("%Y%m%dT%H%M%S%z")
        return f"OBS-{session_date}-{direction}-{stamp}"

    def states(self):
        return reconstruct_states(self.store.read_all())

    def _existing(self, oid: str):
        return self.states().get(oid)

    def on_new_all3(
        self,
        checkpoint: CompletedFiveMinuteCheckpoint,
        previous_directional_all3: str | None,
    ) -> str | None:
        if checkpoint.all3_state not in {"BULLISH_ALL_3", "BEARISH_ALL_3"}:
            return None

        direction: Direction = (
            "BULLISH" if checkpoint.all3_state == "BULLISH_ALL_3" else "BEARISH"
        )
        opposite = "BEARISH_ALL_3" if direction == "BULLISH" else "BULLISH_ALL_3"
        if previous_directional_all3 != opposite:
            return None

        oid = self.observation_id(
            checkpoint.session_date, direction, checkpoint.timestamp
        )
        if self._existing(oid) is not None:
            return oid

        # PROD COMPAT FIX: installed ShadowEngine expects candle1_timestamp,
        # not all3_candle1_timestamp.
        return self.shadow.detect(
            session_date=checkpoint.session_date,
            direction=direction,
            all3_state=checkpoint.all3_state,
            candle1_timestamp=checkpoint.timestamp,
            spot_c1=checkpoint.spot,
            observation_id=oid,
        )

    def on_candle2(
        self,
        oid: str,
        checkpoint: CompletedFiveMinuteCheckpoint,
    ) -> str:
        s = self._existing(oid)
        if s is None:
            raise KeyError(oid)

        expected = f"{s.direction}_ALL_3"
        survived = checkpoint.all3_state == expected

        self.shadow.confirm_candle2(
            oid,
            confirmation_timestamp=checkpoint.timestamp,
            spot_c2=checkpoint.spot,
            all3_survived=survived,
        )
        if not survived:
            return "REJECTED"

        futures_state = checkpoint.futures_oi_state
        if not futures_state:
            self.shadow.incomplete(
                oid,
                checkpoint.timestamp,
                "MISSING_FUTURES_OI_STATE_AT_C2",
            )
            return "INCOMPLETE"

        aligned = futures_state in SUPPORTIVE_FUTURES[s.direction]
        self.shadow.check_futures(
            oid,
            timestamp=checkpoint.timestamp,
            futures_oi_state=futures_state,
            futures_aligned=aligned,
        )
        if not aligned:
            return "REJECTED"

        self.shadow.classify_spot_lag(oid, timestamp=checkpoint.timestamp)
        return "CLASSIFIED"

    def on_exact_option_resolved(
        self,
        oid: str,
        resolution: ExactOptionResolution,
    ) -> str:
        s = self._existing(oid)
        if s is None:
            raise KeyError(oid)
        if s.status != "CLASSIFIED":
            raise ValueError(
                f"{oid} must be CLASSIFIED before option resolution; got {s.status}"
            )
        if not resolution.option_instrument_key:
            self.shadow.incomplete(
                oid, resolution.timestamp, "NO_EXACT_ATM_INSTRUMENT"
            )
            return "INCOMPLETE"

        self.shadow.resolve_option(
            oid,
            timestamp=resolution.timestamp,
            atm_strike=resolution.atm_strike,
            option_instrument_key=resolution.option_instrument_key,
        )
        return "OPTION_RESOLVED"

    def on_exact_next_minute_open(
        self,
        oid: str,
        entry: ExactNextMinuteOpen,
    ) -> str:
        s = self._existing(oid)
        if s is None:
            raise KeyError(oid)
        if s.status != "OPTION_RESOLVED":
            raise ValueError(
                f"{oid} must be OPTION_RESOLVED before entry; got {s.status}"
            )

        self.shadow.open_hypothetical_entry(
            oid,
            entry_timestamp=entry.timestamp,
            entry_price=entry.price,
        )
        return self._existing(oid).status

    def on_option_minute(
        self,
        oid: str,
        bar: CompletedOptionMinute,
    ) -> str:
        return self.shadow.process_option_bar(
            oid,
            bar_timestamp=bar.timestamp,
            open_=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
        )
