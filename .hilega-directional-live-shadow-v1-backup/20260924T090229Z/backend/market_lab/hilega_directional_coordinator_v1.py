from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from typing import Literal

from .hilega_milega_strategy_v1 import (
    FiveMinuteBar,
    HilegaMilegaBullishEngineV1,
    IndicatorSnapshot,
    StrategyEvent,
)
from .hilega_milega_bearish_strategy_v1 import HilegaMilegaBearishEngineV1

Direction = Literal["BULLISH", "BEARISH"]
TradeOwner = Literal["NONE", "BULLISH", "BEARISH"]

BULLISH_ENTRY_EVENTS = {
    "ENTRY_OPENING_BULLISH_CONFIRMED",
    "ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21",
    "ENTRY_PATH1_ROUTE_B_STRUCTURAL",
}
BULLISH_EXIT_EVENTS = {
    "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21",
    "SESSION_CUTOFF_EXIT_1455_OPEN",
}
BEARISH_ENTRY_EVENTS = {
    "ENTRY_OPENING_BEARISH_CONFIRMED",
    "ENTRY_BEARISH_ROUTE_A_CROSS_RSI50_BELOW_WMA21",
    "ENTRY_BEARISH_ROUTE_B_STRUCTURAL",
}
BEARISH_EXIT_EVENTS = {
    "STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21",
    "BEARISH_SESSION_CUTOFF_EXIT_1455_OPEN",
}
BULLISH_ARM_EVENTS = {"PATH1_ARMED_RSI_CROSS_EMA3_UP"}
BEARISH_ARM_EVENTS = {"BEARISH_PATH1_ARMED_RSI_CROSS_EMA3_DOWN"}


@dataclass(frozen=True)
class DirectionalDecision:
    event_time: str
    trade_owner_before: TradeOwner
    trade_owner_after: TradeOwner
    accepted_events: tuple[StrategyEvent, ...]
    suppressed_events: tuple[StrategyEvent, ...]
    bullish_state: str
    bearish_state: str
    bullish_armed: bool
    bearish_armed: bool
    note: str | None = None


class HilegaDirectionalCoordinatorV1:
    """Coordinates the independently validated bullish and bearish engines.

    v1 invariants:
    * At most one ACTIVE trade owner.
    * Opposite ARMED state is informational and may coexist with ACTIVE.
    * Opposite entry is suppressed while one side is ACTIVE.
    * A suppressed opposite entry is preserved as ARMED, not discarded.
    * On an EXIT candle, no new entry is accepted on that same candle.
    * Preserved ARMED state may continue on the next completed candle.
    * No live orders / paper orders are created here.

    This module is intentionally isolated. It does not wire itself into the
    existing live-shadow worker.
    """

    def __init__(
        self,
        *,
        bullish: HilegaMilegaBullishEngineV1 | None = None,
        bearish: HilegaMilegaBearishEngineV1 | None = None,
    ) -> None:
        self.bullish = bullish or HilegaMilegaBullishEngineV1(audit_store=None)
        self.bearish = bearish or HilegaMilegaBearishEngineV1(audit_store=None)
        self.trade_owner: TradeOwner = "NONE"
        self.session_date: date | None = None

    def _reset_owner_if_new_session(self, bar: FiveMinuteBar) -> None:
        if self.session_date != bar.ts.date():
            self.session_date = bar.ts.date()
            self.trade_owner = "NONE"

    @staticmethod
    def _entry_events(events: list[StrategyEvent], direction: Direction) -> list[StrategyEvent]:
        allowed = BULLISH_ENTRY_EVENTS if direction == "BULLISH" else BEARISH_ENTRY_EVENTS
        return [e for e in events if e.event_type in allowed]

    @staticmethod
    def _exit_events(events: list[StrategyEvent], direction: Direction) -> list[StrategyEvent]:
        allowed = BULLISH_EXIT_EVENTS if direction == "BULLISH" else BEARISH_EXIT_EVENTS
        return [e for e in events if e.event_type in allowed]

    @staticmethod
    def _force_informational_armed(engine, direction: Direction, event_time) -> None:
        """Rollback a blocked engine entry to informational ARMED state."""
        engine.session.active = False
        engine.session.armed = True
        engine.session.source = None
        engine.session.entry_time = None
        engine.session.entry_price = None
        if engine.session.armed_time is None:
            engine.session.armed_time = event_time

    @staticmethod
    def _discard_entry_events(events: list[StrategyEvent], direction: Direction) -> tuple[list[StrategyEvent], list[StrategyEvent]]:
        entry_set = BULLISH_ENTRY_EVENTS if direction == "BULLISH" else BEARISH_ENTRY_EVENTS
        accepted = [e for e in events if e.event_type not in entry_set]
        suppressed = [e for e in events if e.event_type in entry_set]
        return accepted, suppressed

    def _coordinate(
        self,
        *,
        bar: FiveMinuteBar,
        bullish_events: list[StrategyEvent],
        bearish_events: list[StrategyEvent],
    ) -> DirectionalDecision:
        owner_before = self.trade_owner
        accepted: list[StrategyEvent] = []
        suppressed: list[StrategyEvent] = []
        note: str | None = None

        b_entries = self._entry_events(bullish_events, "BULLISH")
        s_entries = self._entry_events(bearish_events, "BEARISH")
        b_exits = self._exit_events(bullish_events, "BULLISH")
        s_exits = self._exit_events(bearish_events, "BEARISH")

        # Existing owner has first right to close. The opposite side remains
        # informational on the exit candle and can continue next completed bar.
        if owner_before == "BULLISH":
            accepted.extend(bullish_events)
            if s_entries:
                keep, blocked = self._discard_entry_events(bearish_events, "BEARISH")
                accepted.extend(keep)
                suppressed.extend(blocked)
                self._force_informational_armed(self.bearish, "BEARISH", bar.ts)
            else:
                accepted.extend(bearish_events)

            if b_exits:
                self.trade_owner = "NONE"
                if s_entries:
                    note = "BULLISH_EXIT; SAME_CANDLE_BEARISH_ENTRY_BLOCKED; PRESERVE_BEARISH_ARMED"
                else:
                    note = "BULLISH_EXIT; NO_SAME_CANDLE_BEARISH_ENTRY"
            return self._decision(bar, owner_before, accepted, suppressed, note)

        if owner_before == "BEARISH":
            accepted.extend(bearish_events)
            if b_entries:
                keep, blocked = self._discard_entry_events(bullish_events, "BULLISH")
                accepted.extend(keep)
                suppressed.extend(blocked)
                self._force_informational_armed(self.bullish, "BULLISH", bar.ts)
            else:
                accepted.extend(bullish_events)

            if s_exits:
                self.trade_owner = "NONE"
                if b_entries:
                    note = "BEARISH_EXIT; SAME_CANDLE_BULLISH_ENTRY_BLOCKED; PRESERVE_BULLISH_ARMED"
                else:
                    note = "BEARISH_EXIT; NO_SAME_CANDLE_BULLISH_ENTRY"
            return self._decision(bar, owner_before, accepted, suppressed, note)

        # No active owner. If both sides somehow emit an entry on one candle,
        # accept neither; preserve both as informational ARMED for the next bar.
        if b_entries and s_entries:
            b_keep, b_blocked = self._discard_entry_events(bullish_events, "BULLISH")
            s_keep, s_blocked = self._discard_entry_events(bearish_events, "BEARISH")
            accepted.extend(b_keep)
            accepted.extend(s_keep)
            suppressed.extend(b_blocked)
            suppressed.extend(s_blocked)
            self._force_informational_armed(self.bullish, "BULLISH", bar.ts)
            self._force_informational_armed(self.bearish, "BEARISH", bar.ts)
            note = "DIRECTIONAL_CONFLICT; BOTH_ENTRIES_BLOCKED"
            return self._decision(bar, owner_before, accepted, suppressed, note)

        accepted.extend(bullish_events)
        accepted.extend(bearish_events)

        if b_entries:
            self.trade_owner = "BULLISH"
            # Any stale opposite active state is forbidden.
            self.bearish.session.active = False
        elif s_entries:
            self.trade_owner = "BEARISH"
            self.bullish.session.active = False

        return self._decision(bar, owner_before, accepted, suppressed, note)

    def _decision(
        self,
        bar: FiveMinuteBar,
        owner_before: TradeOwner,
        accepted: list[StrategyEvent],
        suppressed: list[StrategyEvent],
        note: str | None,
    ) -> DirectionalDecision:
        if self.bullish.session.active and self.bearish.session.active:
            raise RuntimeError("directional invariant violated: both sides ACTIVE")
        if self.trade_owner == "BULLISH" and not self.bullish.session.active:
            raise RuntimeError("directional invariant violated: bullish owner without bullish ACTIVE")
        if self.trade_owner == "BEARISH" and not self.bearish.session.active:
            raise RuntimeError("directional invariant violated: bearish owner without bearish ACTIVE")

        return DirectionalDecision(
            event_time=bar.ts.isoformat(),
            trade_owner_before=owner_before,
            trade_owner_after=self.trade_owner,
            accepted_events=tuple(accepted),
            suppressed_events=tuple(suppressed),
            bullish_state=self.bullish.session.name,
            bearish_state=self.bearish.session.name,
            bullish_armed=bool(self.bullish.session.armed),
            bearish_armed=bool(self.bearish.session.armed),
            note=note,
        )

    def on_bar(self, bar: FiveMinuteBar) -> DirectionalDecision:
        """Production-style indicator path; not wired into live worker in this phase."""
        self._reset_owner_if_new_session(bar)
        bullish_events = self.bullish.on_bar(bar)
        bearish_events = self.bearish.on_bar(bar)
        return self._coordinate(
            bar=bar,
            bullish_events=bullish_events,
            bearish_events=bearish_events,
        )

    def process_enriched_bar_for_test(
        self, bar: FiveMinuteBar, indicators: IndicatorSnapshot
    ) -> DirectionalDecision:
        """Deterministic test path using one shared indicator snapshot."""
        self._reset_owner_if_new_session(bar)
        bullish_events = self.bullish.process_enriched_bar_for_test(bar, indicators)
        bearish_events = self.bearish.process_enriched_bar_for_test(bar, indicators)
        return self._coordinate(
            bar=bar,
            bullish_events=bullish_events,
            bearish_events=bearish_events,
        )
