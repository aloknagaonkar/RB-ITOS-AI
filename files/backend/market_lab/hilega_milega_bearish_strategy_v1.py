from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any

from .hilega_milega_strategy_v1 import (
    FiveMinuteBar,
    HilegaMilegaIndicatorEngineV1,
    IndicatorSnapshot,
    StrategyEvent,
)
from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1

STRATEGY_ID = "HILEGA_MILEGA_BEARISH_SHADOW_V1"
STRATEGY_VERSION = "1.0.0"
TIMEFRAME = "5m"
SESSION_CUTOFF = "14:55"
OBSERVATION_ONLY = True
EXECUTION_ENABLED = False
PAPER_ORDER_ENABLED = False


@dataclass
class BearishSessionState:
    session_date: date | None = None
    active: bool = False
    armed: bool = False
    opening_candidate: bool = False
    opening_holding: bool = False
    session_locked: bool = False
    source: str | None = None
    entry_time: datetime | None = None
    entry_price: float | None = None
    armed_time: datetime | None = None

    @property
    def name(self) -> str:
        if self.session_locked:
            return "SESSION_LOCKED"
        if self.active:
            return "BEARISH_ACTIVE"
        if self.armed:
            return "BEARISH_PATH1_ARMED"
        if self.opening_holding:
            return "BEARISH_OPENING_HOLD"
        if self.opening_candidate:
            return "BEARISH_OPENING_CANDIDATE"
        return "BEARISH_PATH1_IDLE"


class HilegaMilegaBearishEngineV1:
    """Candidate bearish mirror of the frozen Hilega-Milega bullish engine.

    Phase B1/B2 rules under validation:
    * Opening path: 09:15 full bearish alignment -> 09:20 RSI<WMA ->
      09:25 RSI<WMA.
    * Path1 arm: RSI crosses EMA3 downward.
    * Route A: same cross candle RSI<50 and RSI<WMA21.
    * Route B: armed and (RSI<WMA21 or EMA3<WMA21) and RSI/EMA falling.
    * Exit: first RSI cross above WMA21.
    * 14:55 hard cutoff: close active at 14:55 OPEN, cancel state, no new entry.

    This module is intentionally independent of the production bullish engine.
    No live PE integration or directional arbitration is performed here.
    """

    def __init__(self, *, audit_store: ShadowStepAuditStoreV1 | None = None) -> None:
        self.audit_store = audit_store
        self.indicators = HilegaMilegaIndicatorEngineV1()
        self.session = BearishSessionState()
        self.previous_indicators: IndicatorSnapshot | None = None
        self.previous_bar: FiveMinuteBar | None = None

    @staticmethod
    def _cross_up(a0: float | None, b0: float | None, a1: float | None, b1: float | None) -> bool:
        return None not in (a0, b0, a1, b1) and a0 <= b0 and a1 > b1

    @staticmethod
    def _cross_down(a0: float | None, b0: float | None, a1: float | None, b1: float | None) -> bool:
        return None not in (a0, b0, a1, b1) and a0 >= b0 and a1 < b1

    @staticmethod
    def _full_alignment(ind: IndicatorSnapshot) -> bool:
        return (
            ind.ready
            and ind.rsi9 < 50
            and ind.ema3_rsi < 50
            and ind.wma21_rsi < 50
            and ind.rsi9 < ind.ema3_rsi < ind.wma21_rsi
        )

    def _audit(self, bar: FiveMinuteBar, stage: str, status: str, payload: dict[str, Any]) -> None:
        if self.audit_store is None:
            return
        self.audit_store.append(
            event_time=bar.ts,
            checkpoint=bar.ts,
            stage=stage,
            status=status,
            payload={
                "strategy_id": STRATEGY_ID,
                "strategy_version": STRATEGY_VERSION,
                **payload,
            },
        )

    def _reset_session(self, session_date: date, bar: FiveMinuteBar) -> None:
        prior = self.session
        if prior.session_date == session_date:
            return
        if prior.session_date is not None:
            self._audit(
                bar,
                "SESSION_TRANSITION",
                "RESET",
                {
                    "previous_session_date": prior.session_date.isoformat(),
                    "new_session_date": session_date.isoformat(),
                    "previous_state": prior.name,
                    "previous_active": prior.active,
                },
            )
        self.session = BearishSessionState(session_date=session_date)
        self.previous_indicators = None
        self.previous_bar = None

    def on_bar(self, bar: FiveMinuteBar) -> list[StrategyEvent]:
        self._reset_session(bar.ts.date(), bar)
        ind = self.indicators.update(bar.close)
        self._audit(
            bar,
            "INDICATOR_CALCULATION",
            "READY" if ind.ready else "WARMUP",
            {
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "rsi9": ind.rsi9,
                "ema3_rsi": ind.ema3_rsi,
                "wma21_rsi": ind.wma21_rsi,
            },
        )
        events = self._process_enriched_bar(bar, ind)
        self.previous_indicators = ind
        self.previous_bar = bar
        return events

    def _emit(
        self,
        *,
        bar: FiveMinuteBar,
        event_type: str,
        before: str,
        source: str | None = None,
        price: float | None = None,
        exit_reason: str | None = None,
        points: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> StrategyEvent:
        event = StrategyEvent(
            event_type=event_type,
            event_time=bar.ts,
            source=source,
            state_before=before,
            state_after=self.session.name,
            price=price,
            entry_time=self.session.entry_time,
            entry_price=self.session.entry_price,
            exit_reason=exit_reason,
            points=points,
            details=details,
        )
        self._audit(
            bar,
            "STRATEGY_TRANSITION",
            event_type,
            {
                **asdict(event),
                "event_time": event.event_time.isoformat(),
                "entry_time": event.entry_time.isoformat() if event.entry_time else None,
            },
        )
        return event

    def _decision_payload(self, ind: IndicatorSnapshot) -> dict[str, Any]:
        prev = self.previous_indicators
        rsi_falling = bool(prev and prev.rsi9 is not None and ind.rsi9 is not None and ind.rsi9 < prev.rsi9)
        ema_falling = bool(
            prev
            and prev.ema3_rsi is not None
            and ind.ema3_rsi is not None
            and ind.ema3_rsi < prev.ema3_rsi
        )
        rsi_cross_ema_down = bool(
            prev and self._cross_down(prev.rsi9, prev.ema3_rsi, ind.rsi9, ind.ema3_rsi)
        )
        rsi_cross_wma_up = bool(
            prev and self._cross_up(prev.rsi9, prev.wma21_rsi, ind.rsi9, ind.wma21_rsi)
        )
        return {
            "rsi9": ind.rsi9,
            "ema3_rsi": ind.ema3_rsi,
            "wma21_rsi": ind.wma21_rsi,
            "previous_rsi9": prev.rsi9 if prev else None,
            "previous_ema3_rsi": prev.ema3_rsi if prev else None,
            "previous_wma21_rsi": prev.wma21_rsi if prev else None,
            "rsi_falling": rsi_falling,
            "ema_falling": ema_falling,
            "rsi_cross_ema_down": rsi_cross_ema_down,
            "rsi_cross_wma_up": rsi_cross_wma_up,
            "rsi_lt_50": ind.rsi9 is not None and ind.rsi9 < 50,
            "rsi_lt_wma": ind.ready and ind.rsi9 < ind.wma21_rsi,
            "ema_lt_wma": ind.ready and ind.ema3_rsi < ind.wma21_rsi,
            "full_alignment": self._full_alignment(ind),
        }

    @staticmethod
    def _route_a_fail_reasons(d: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        if not d["rsi_lt_50"]:
            reasons.append("RSI_NOT_BELOW_50")
        if not d["rsi_lt_wma"]:
            reasons.append("RSI_NOT_BELOW_WMA21")
        return reasons

    @staticmethod
    def _route_b_fail_reasons(d: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        if not (d["rsi_lt_wma"] or d["ema_lt_wma"]):
            reasons.append("NEITHER_RSI_NOR_EMA_BELOW_WMA21")
        if not d["rsi_falling"]:
            reasons.append("RSI_NOT_FALLING")
        if not d["ema_falling"]:
            reasons.append("EMA_NOT_FALLING")
        return reasons

    def _audit_decision_result(
        self,
        bar: FiveMinuteBar,
        *,
        state_before: str,
        d: dict[str, Any],
        events: list[StrategyEvent],
        note: str | None = None,
    ) -> None:
        event_types = [e.event_type for e in events]
        selected_route = None
        if "ENTRY_BEARISH_ROUTE_A_CROSS_RSI50_BELOW_WMA21" in event_types:
            selected_route = "ROUTE_A"
        elif "ENTRY_BEARISH_ROUTE_B_STRUCTURAL" in event_types:
            selected_route = "ROUTE_B"
        elif "ENTRY_OPENING_BEARISH_CONFIRMED" in event_types:
            selected_route = "OPENING_PATH"
        fresh_cross = bool(d.get("rsi_cross_ema_down"))
        route_a_eligible = fresh_cross and state_before != "BEARISH_ACTIVE"
        route_b_eligible = (
            (state_before == "BEARISH_PATH1_ARMED" or fresh_cross)
            and state_before != "BEARISH_ACTIVE"
        )
        self._audit(
            bar,
            "STRATEGY_DECISION_RESULT",
            "COMPLETE",
            {
                "direction": "BEARISH",
                "time": bar.ts.strftime("%H:%M"),
                "state_before": state_before,
                "state_after": self.session.name,
                "events_emitted": event_types,
                "selected_route": selected_route,
                "route_b_suppressed_by_route_a_priority": selected_route == "ROUTE_A" and route_b_eligible and not self._route_b_fail_reasons(d),
                "route_a_eligible": route_a_eligible,
                "route_a_pass": route_a_eligible and not self._route_a_fail_reasons(d),
                "route_a_fail_reasons": self._route_a_fail_reasons(d) if route_a_eligible else [],
                "route_b_eligible": route_b_eligible,
                "route_b_pass": route_b_eligible and not self._route_b_fail_reasons(d),
                "route_b_fail_reasons": self._route_b_fail_reasons(d) if route_b_eligible else [],
                "structural_exit_condition": bool(d.get("rsi_cross_wma_up")),
                "new_entries_allowed": (
                    self.session.name != "SESSION_LOCKED"
                    and (bar.ts + timedelta(minutes=5)).strftime("%H:%M") < SESSION_CUTOFF
                ),
                "note": note,
                **d,
            },
        )

    @staticmethod
    def _bearish_points(entry_price: float | None, exit_price: float) -> float | None:
        return None if entry_price is None else entry_price - exit_price

    def on_session_cutoff(self, cutoff_ts: datetime, open_price: float) -> list[StrategyEvent]:
        self._reset_session(
            cutoff_ts.date(),
            FiveMinuteBar(cutoff_ts, open_price, open_price, open_price, open_price, None),
        )
        if cutoff_ts.strftime("%H:%M") < SESSION_CUTOFF:
            raise ValueError("session cutoff cannot be applied before 14:55")
        if self.session.session_locked:
            return []
        bar = FiveMinuteBar(cutoff_ts, open_price, open_price, open_price, open_price, None)
        events: list[StrategyEvent] = []
        if self.session.active:
            before = self.session.name
            source = self.session.source
            entry_time = self.session.entry_time
            entry_price = self.session.entry_price
            points = self._bearish_points(entry_price, open_price)
            self.session.active = False
            self.session.source = None
            self.session.entry_time = None
            self.session.entry_price = None
            events.append(
                self._emit(
                    bar=bar,
                    event_type="BEARISH_SESSION_CUTOFF_EXIT_1455_OPEN",
                    before=before,
                    source=source,
                    price=open_price,
                    exit_reason="SESSION_CUTOFF_14_55_OPEN",
                    points=points,
                    details={
                        "original_entry_time": entry_time.isoformat() if entry_time else None,
                        "live_open_time_cutoff": True,
                    },
                )
            )
        if self.session.armed:
            before = self.session.name
            self.session.armed = False
            self.session.armed_time = None
            events.append(
                self._emit(
                    bar=bar,
                    event_type="BEARISH_SESSION_CUTOFF_ARM_CANCELLED",
                    before=before,
                )
            )
        self.session.opening_candidate = False
        self.session.opening_holding = False
        before_lock = self.session.name
        self.session.session_locked = True
        events.append(
            self._emit(
                bar=bar,
                event_type="BEARISH_SESSION_LOCKED_1455",
                before=before_lock,
                details={"new_entries_allowed": False, "live_open_time_cutoff": True},
            )
        )
        self._audit(
            bar,
            "STRATEGY_DECISION_RESULT",
            "COMPLETE",
            {
                "direction": "BEARISH",
                "time": "14:55",
                "state_before": before_lock,
                "state_after": self.session.name,
                "events_emitted": [e.event_type for e in events],
                "new_entries_allowed": False,
                "note": "SESSION_CUTOFF_OPEN_TIME",
            },
        )
        return events

    def _process_enriched_bar(self, bar: FiveMinuteBar, ind: IndicatorSnapshot) -> list[StrategyEvent]:
        events: list[StrategyEvent] = []
        t = bar.ts.strftime("%H:%M")

        if not ind.ready:
            self._audit(bar, "STRATEGY_DECISION", "INDICATOR_WARMUP", {"state": self.session.name})
            return events

        d = self._decision_payload(ind)
        decision_state_before = self.session.name
        self._audit(
            bar,
            "STRATEGY_DECISION",
            "EVALUATED",
            {
                "direction": "BEARISH",
                "state_before": decision_state_before,
                "time": t,
                "bar_open": bar.open,
                "bar_high": bar.high,
                "bar_low": bar.low,
                "bar_close": bar.close,
                "bar_volume": bar.volume,
                **d,
            },
        )

        if t >= SESSION_CUTOFF:
            if not self.session.session_locked:
                if self.session.active:
                    before = self.session.name
                    source = self.session.source
                    entry_time = self.session.entry_time
                    entry_price = self.session.entry_price
                    points = self._bearish_points(entry_price, bar.open)
                    self.session.active = False
                    self.session.source = None
                    self.session.entry_time = None
                    self.session.entry_price = None
                    events.append(
                        self._emit(
                            bar=bar,
                            event_type="BEARISH_SESSION_CUTOFF_EXIT_1455_OPEN",
                            before=before,
                            source=source,
                            price=bar.open,
                            exit_reason="SESSION_CUTOFF_14_55_OPEN",
                            points=points,
                            details={"original_entry_time": entry_time.isoformat() if entry_time else None},
                        )
                    )
                if self.session.armed:
                    before = self.session.name
                    self.session.armed = False
                    self.session.armed_time = None
                    events.append(
                        self._emit(
                            bar=bar,
                            event_type="BEARISH_SESSION_CUTOFF_ARM_CANCELLED",
                            before=before,
                        )
                    )
                self.session.opening_candidate = False
                self.session.opening_holding = False
                self.session.session_locked = True
                events.append(
                    self._emit(
                        bar=bar,
                        event_type="BEARISH_SESSION_LOCKED_1455",
                        before="BEARISH_PATH1_IDLE" if not events else events[-1].state_after,
                        details={"new_entries_allowed": False},
                    )
                )
            else:
                self._audit(
                    bar,
                    "STRATEGY_DECISION",
                    "NO_TRADE_AFTER_CUTOFF",
                    {"state": self.session.name, "new_entries_allowed": False},
                )
            self._audit_decision_result(
                bar, state_before=decision_state_before, d=d, events=events, note="SESSION_CUTOFF"
            )
            return events

        # Structural bearish exit: RSI crosses upward through WMA21.
        if self.session.active and d["rsi_cross_wma_up"]:
            before = self.session.name
            source = self.session.source
            entry_time = self.session.entry_time
            entry_price = self.session.entry_price
            points = self._bearish_points(entry_price, bar.close)
            self.session.active = False
            self.session.source = None
            self.session.entry_time = None
            self.session.entry_price = None
            self.session.armed = False
            self.session.armed_time = None
            events.append(
                self._emit(
                    bar=bar,
                    event_type="STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21",
                    before=before,
                    source=source,
                    price=bar.close,
                    exit_reason="RSI_CROSS_ABOVE_WMA21",
                    points=points,
                    details={"original_entry_time": entry_time.isoformat() if entry_time else None},
                )
            )

        # Opening bearish path.
        if t == "09:15" and d["full_alignment"]:
            before = self.session.name
            self.session.opening_candidate = True
            events.append(
                self._emit(bar=bar, event_type="OPENING_BEARISH_CANDIDATE_0915", before=before)
            )
        elif t == "09:20" and self.session.opening_candidate:
            before = self.session.name
            if d["rsi_lt_wma"]:
                self.session.opening_holding = True
                events.append(
                    self._emit(bar=bar, event_type="OPENING_BEARISH_HOLD_0920", before=before)
                )
            else:
                self.session.opening_candidate = False
                self.session.opening_holding = False
                events.append(
                    self._emit(bar=bar, event_type="OPENING_BEARISH_REJECTED_0920", before=before)
                )
        elif t == "09:25" and self.session.opening_candidate and self.session.opening_holding:
            before = self.session.name
            if d["rsi_lt_wma"] and not self.session.active:
                self.session.active = True
                self.session.source = "BEARISH_OPENING_PATH"
                self.session.entry_time = bar.ts
                self.session.entry_price = bar.close
                self.session.armed = False
                self.session.armed_time = None
                events.append(
                    self._emit(
                        bar=bar,
                        event_type="ENTRY_OPENING_BEARISH_CONFIRMED",
                        before=before,
                        source=self.session.source,
                        price=bar.close,
                    )
                )
            else:
                events.append(
                    self._emit(bar=bar, event_type="OPENING_BEARISH_REJECTED_0925", before=before)
                )
            self.session.opening_candidate = False
            self.session.opening_holding = False

        entry_boundary_open = (bar.ts + timedelta(minutes=5)).strftime("%H:%M") < SESSION_CUTOFF

        # Path1 arming and bearish Route A.
        if not self.session.active and d["rsi_cross_ema_down"]:
            before = self.session.name
            self.session.armed = True
            self.session.armed_time = bar.ts
            if entry_boundary_open and d["rsi_lt_50"] and d["rsi_lt_wma"]:
                self.session.active = True
                self.session.source = "BEARISH_ROUTE_A_CROSS_RSI50_BELOW_WMA21"
                self.session.entry_time = bar.ts
                self.session.entry_price = bar.close
                self.session.armed = False
                self.session.armed_time = None
                events.append(
                    self._emit(
                        bar=bar,
                        event_type="ENTRY_BEARISH_ROUTE_A_CROSS_RSI50_BELOW_WMA21",
                        before=before,
                        source=self.session.source,
                        price=bar.close,
                    )
                )
            else:
                events.append(
                    self._emit(
                        bar=bar,
                        event_type="BEARISH_PATH1_ARMED_RSI_CROSS_EMA3_DOWN",
                        before=before,
                    )
                )

        # Bearish Route B can confirm on the same cross candle or later armed candle.
        if (
            not self.session.active
            and self.session.armed
            and (d["rsi_lt_wma"] or d["ema_lt_wma"])
            and d["rsi_falling"]
            and d["ema_falling"]
            and entry_boundary_open
        ):
            before = self.session.name
            self.session.active = True
            self.session.source = "BEARISH_ROUTE_B_STRUCTURAL"
            self.session.entry_time = bar.ts
            self.session.entry_price = bar.close
            self.session.armed = False
            self.session.armed_time = None
            events.append(
                self._emit(
                    bar=bar,
                    event_type="ENTRY_BEARISH_ROUTE_B_STRUCTURAL",
                    before=before,
                    source=self.session.source,
                    price=bar.close,
                )
            )

        self._audit_decision_result(bar, state_before=decision_state_before, d=d, events=events)
        return events

    def process_enriched_bar_for_test(
        self, bar: FiveMinuteBar, indicators: IndicatorSnapshot
    ) -> list[StrategyEvent]:
        self._reset_session(bar.ts.date(), bar)
        events = self._process_enriched_bar(bar, indicators)
        self.previous_indicators = indicators
        self.previous_bar = bar
        return events
