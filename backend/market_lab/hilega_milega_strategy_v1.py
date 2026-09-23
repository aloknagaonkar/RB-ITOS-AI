from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1

STRATEGY_ID = "HILEGA_MILEGA_BULLISH_SHADOW_V1"
STRATEGY_VERSION = "1.0.0"
TIMEFRAME = "5m"
SESSION_CUTOFF = "14:55"
OBSERVATION_ONLY = True
EXECUTION_ENABLED = False
PAPER_ORDER_ENABLED = False


@dataclass(frozen=True)
class FiveMinuteBar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
            raise ValueError("bar timestamp must be timezone-aware")


@dataclass(frozen=True)
class IndicatorSnapshot:
    rsi9: float | None
    ema3_rsi: float | None
    wma21_rsi: float | None

    @property
    def ready(self) -> bool:
        return None not in (self.rsi9, self.ema3_rsi, self.wma21_rsi)


@dataclass(frozen=True)
class StrategyEvent:
    event_type: str
    event_time: datetime
    source: str | None
    state_before: str
    state_after: str
    price: float | None = None
    entry_time: datetime | None = None
    entry_price: float | None = None
    exit_reason: str | None = None
    points: float | None = None
    details: dict[str, Any] | None = None


@dataclass
class SessionState:
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
            return "BULLISH_ACTIVE"
        if self.armed:
            return "PATH1_ARMED"
        if self.opening_holding:
            return "OPENING_HOLD"
        if self.opening_candidate:
            return "OPENING_CANDIDATE"
        return "PATH1_IDLE"


class HilegaMilegaIndicatorEngineV1:
    """Streaming Pine-compatible RSI9 -> EMA3/WMA21 indicator chain.

    Indicator history intentionally continues across sessions. Strategy state does
    not. This mirrors the validated historical scripts, where prior sessions warm
    the indicators before the target session begins.
    """

    def __init__(self) -> None:
        self._last_close: float | None = None
        self._seed_gains: list[float] = []
        self._seed_losses: list[float] = []
        self._avg_gain: float | None = None
        self._avg_loss: float | None = None
        self._rsi_count = 0
        self._ema3: float | None = None
        self._wma_window: deque[float] = deque(maxlen=21)

    @staticmethod
    def _rsi_from_avgs(avg_gain: float, avg_loss: float) -> float:
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return 100.0 - 100.0 / (1.0 + rs)

    def update(self, close: float) -> IndicatorSnapshot:
        close = float(close)
        rsi: float | None = None

        if self._last_close is None:
            self._last_close = close
            return IndicatorSnapshot(None, None, None)

        delta = close - self._last_close
        self._last_close = close
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)

        if self._avg_gain is None or self._avg_loss is None:
            self._seed_gains.append(gain)
            self._seed_losses.append(loss)
            if len(self._seed_gains) == 9:
                self._avg_gain = sum(self._seed_gains) / 9.0
                self._avg_loss = sum(self._seed_losses) / 9.0
                rsi = self._rsi_from_avgs(self._avg_gain, self._avg_loss)
        else:
            self._avg_gain = (8.0 * self._avg_gain + gain) / 9.0
            self._avg_loss = (8.0 * self._avg_loss + loss) / 9.0
            rsi = self._rsi_from_avgs(self._avg_gain, self._avg_loss)

        if rsi is None:
            return IndicatorSnapshot(None, self._ema3, None)

        self._rsi_count += 1
        self._ema3 = rsi if self._ema3 is None else 0.5 * rsi + 0.5 * self._ema3
        self._wma_window.append(rsi)

        wma = None
        if len(self._wma_window) == 21:
            den = 21 * 22 / 2
            wma = sum((i + 1) * value for i, value in enumerate(self._wma_window)) / den

        return IndicatorSnapshot(rsi, self._ema3, wma)


class HilegaMilegaBullishEngineV1:
    """Canonical Hilega-Milega bullish strategy state machine.

    Approved strategy rules only:
    * Opening path: 09:15 FULL -> 09:20 RSI>WMA -> 09:25 RSI>WMA.
    * Path1 arm: RSI crosses EMA3 upward.
    * Route A: same cross candle RSI>50 and RSI>WMA21.
    * Route B: armed and (RSI>WMA21 or EMA3>WMA21) and RSI/EMA rising.
    * Exit: first RSI cross below WMA21.
    * 14:55 hard cutoff: close active at 14:55 OPEN, cancel state, no new entry.

    No WMA3/gap/3-candle/profit-management research rules are present here.
    """

    def __init__(self, *, audit_store: ShadowStepAuditStoreV1 | None = None) -> None:
        self.audit_store = audit_store
        self.indicators = HilegaMilegaIndicatorEngineV1()
        self.session = SessionState()
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
            and ind.rsi9 > 50
            and ind.ema3_rsi > 50
            and ind.wma21_rsi > 50
            and ind.rsi9 > ind.ema3_rsi > ind.wma21_rsi
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
        self.session = SessionState(session_date=session_date)
        # Strategy comparisons never cross the overnight boundary. Indicator
        # warmup continues across sessions, but RSI/EMA/WMA cross/rising checks
        # start fresh from the first bar of each session, matching the validated
        # per-session research replay.
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
        rsi_up = bool(prev and prev.rsi9 is not None and ind.rsi9 is not None and ind.rsi9 > prev.rsi9)
        ema_up = bool(
            prev
            and prev.ema3_rsi is not None
            and ind.ema3_rsi is not None
            and ind.ema3_rsi > prev.ema3_rsi
        )
        rsi_cross_ema = bool(
            prev
            and self._cross_up(prev.rsi9, prev.ema3_rsi, ind.rsi9, ind.ema3_rsi)
        )
        rsi_cross_down_wma = bool(
            prev
            and self._cross_down(prev.rsi9, prev.wma21_rsi, ind.rsi9, ind.wma21_rsi)
        )
        return {
            "rsi9": ind.rsi9,
            "ema3_rsi": ind.ema3_rsi,
            "wma21_rsi": ind.wma21_rsi,
            "previous_rsi9": prev.rsi9 if prev else None,
            "previous_ema3_rsi": prev.ema3_rsi if prev else None,
            "previous_wma21_rsi": prev.wma21_rsi if prev else None,
            "rsi_rising": rsi_up,
            "ema_rising": ema_up,
            "rsi_cross_ema_up": rsi_cross_ema,
            "rsi_cross_wma_down": rsi_cross_down_wma,
            "rsi_gt_50": ind.rsi9 is not None and ind.rsi9 > 50,
            "rsi_gt_wma": ind.ready and ind.rsi9 > ind.wma21_rsi,
            "ema_gt_wma": ind.ready and ind.ema3_rsi > ind.wma21_rsi,
            "full_alignment": self._full_alignment(ind),
        }

    @staticmethod
    def _route_a_fail_reasons(d: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        if not d["rsi_gt_50"]:
            reasons.append("RSI_NOT_ABOVE_50")
        if not d["rsi_gt_wma"]:
            reasons.append("RSI_NOT_ABOVE_WMA21")
        return reasons

    @staticmethod
    def _route_b_fail_reasons(d: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        if not (d["rsi_gt_wma"] or d["ema_gt_wma"]):
            reasons.append("NEITHER_RSI_NOR_EMA_ABOVE_WMA21")
        if not d["rsi_rising"]:
            reasons.append("RSI_NOT_RISING")
        if not d["ema_rising"]:
            reasons.append("EMA_NOT_RISING")
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
        fresh_cross = bool(d.get("rsi_cross_ema_up"))
        route_a_eligible = fresh_cross and state_before != "BULLISH_ACTIVE"
        route_b_eligible = (
            (state_before == "PATH1_ARMED" or fresh_cross)
            and state_before != "BULLISH_ACTIVE"
        )
        self._audit(
            bar,
            "STRATEGY_DECISION_RESULT",
            "COMPLETE",
            {
                "time": bar.ts.strftime("%H:%M"),
                "state_before": state_before,
                "state_after": self.session.name,
                "events_emitted": event_types,
                "route_a_eligible": route_a_eligible,
                "route_a_pass": route_a_eligible and not self._route_a_fail_reasons(d),
                "route_a_fail_reasons": self._route_a_fail_reasons(d) if route_a_eligible else [],
                "route_b_eligible": route_b_eligible,
                "route_b_pass": route_b_eligible and not self._route_b_fail_reasons(d),
                "route_b_fail_reasons": self._route_b_fail_reasons(d) if route_b_eligible else [],
                "structural_exit_condition": bool(d.get("rsi_cross_wma_down")),
                "new_entries_allowed": self.session.name != "SESSION_LOCKED",
                "note": note,
                **d,
            },
        )

    def _process_enriched_bar(
        self, bar: FiveMinuteBar, ind: IndicatorSnapshot
    ) -> list[StrategyEvent]:
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
            {"state_before": decision_state_before, "time": t, **d},
        )

        # Hard cutoff is evaluated before every other strategy transition.
        if t >= SESSION_CUTOFF:
            if not self.session.session_locked:
                if self.session.active:
                    before = self.session.name
                    source = self.session.source
                    entry_time = self.session.entry_time
                    entry_price = self.session.entry_price
                    points = None if entry_price is None else bar.open - entry_price
                    self.session.active = False
                    self.session.source = None
                    self.session.entry_time = None
                    self.session.entry_price = None
                    events.append(
                        self._emit(
                            bar=bar,
                            event_type="SESSION_CUTOFF_EXIT_1455_OPEN",
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
                            event_type="SESSION_CUTOFF_ARM_CANCELLED",
                            before=before,
                        )
                    )
                self.session.opening_candidate = False
                self.session.opening_holding = False
                self.session.session_locked = True
                events.append(
                    self._emit(
                        bar=bar,
                        event_type="SESSION_LOCKED_1455",
                        before="PATH1_IDLE" if not events else events[-1].state_after,
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

        # Immediate structural exit first, preserving current validator ordering.
        if self.session.active and d["rsi_cross_wma_down"]:
            before = self.session.name
            source = self.session.source
            entry_time = self.session.entry_time
            entry_price = self.session.entry_price
            points = None if entry_price is None else bar.close - entry_price
            self.session.active = False
            self.session.source = None
            self.session.entry_time = None
            self.session.entry_price = None
            self.session.armed = False
            self.session.armed_time = None
            events.append(
                self._emit(
                    bar=bar,
                    event_type="STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21",
                    before=before,
                    source=source,
                    price=bar.close,
                    exit_reason="RSI_CROSS_BELOW_WMA21",
                    points=points,
                    details={"original_entry_time": entry_time.isoformat() if entry_time else None},
                )
            )

        # Opening path.
        if t == "09:15" and d["full_alignment"]:
            before = self.session.name
            self.session.opening_candidate = True
            events.append(self._emit(bar=bar, event_type="OPENING_CANDIDATE_0915", before=before))
        elif t == "09:20" and self.session.opening_candidate:
            before = self.session.name
            if d["rsi_gt_wma"]:
                self.session.opening_holding = True
                events.append(self._emit(bar=bar, event_type="OPENING_HOLD_0920", before=before))
            else:
                self.session.opening_candidate = False
                self.session.opening_holding = False
                events.append(self._emit(bar=bar, event_type="OPENING_REJECTED_0920", before=before))
        elif t == "09:25" and self.session.opening_candidate and self.session.opening_holding:
            before = self.session.name
            if d["rsi_gt_wma"] and not self.session.active:
                self.session.active = True
                self.session.source = "OPENING_PATH"
                self.session.entry_time = bar.ts
                self.session.entry_price = bar.close
                self.session.armed = False
                self.session.armed_time = None
                events.append(
                    self._emit(
                        bar=bar,
                        event_type="ENTRY_OPENING_BULLISH_CONFIRMED",
                        before=before,
                        source=self.session.source,
                        price=bar.close,
                    )
                )
            else:
                events.append(self._emit(bar=bar, event_type="OPENING_REJECTED_0925", before=before))
            self.session.opening_candidate = False
            self.session.opening_holding = False

        # Path1 arming and Route A.
        if not self.session.active and d["rsi_cross_ema_up"]:
            before = self.session.name
            self.session.armed = True
            self.session.armed_time = bar.ts

            if d["rsi_gt_50"] and d["rsi_gt_wma"]:
                self.session.active = True
                self.session.source = "PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21"
                self.session.entry_time = bar.ts
                self.session.entry_price = bar.close
                self.session.armed = False
                self.session.armed_time = None
                events.append(
                    self._emit(
                        bar=bar,
                        event_type="ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21",
                        before=before,
                        source=self.session.source,
                        price=bar.close,
                    )
                )
            else:
                events.append(
                    self._emit(
                        bar=bar,
                        event_type="PATH1_ARMED_RSI_CROSS_EMA3_UP",
                        before=before,
                    )
                )

        # Route B can confirm on the same cross candle or any later armed candle.
        if (
            not self.session.active
            and self.session.armed
            and (d["rsi_gt_wma"] or d["ema_gt_wma"])
            and d["rsi_rising"]
            and d["ema_rising"]
        ):
            before = self.session.name
            self.session.active = True
            self.session.source = "PATH1_ROUTE_B_STRUCTURAL"
            self.session.entry_time = bar.ts
            self.session.entry_price = bar.close
            self.session.armed = False
            self.session.armed_time = None
            events.append(
                self._emit(
                    bar=bar,
                    event_type="ENTRY_PATH1_ROUTE_B_STRUCTURAL",
                    before=before,
                    source=self.session.source,
                    price=bar.close,
                )
            )

        self._audit_decision_result(
            bar, state_before=decision_state_before, d=d, events=events
        )
        return events

    # Deliberately exposed only for deterministic state-machine unit tests.
    # Production/replay callers should use on_bar() so indicators are canonical.
    def process_enriched_bar_for_test(
        self, bar: FiveMinuteBar, indicators: IndicatorSnapshot
    ) -> list[StrategyEvent]:
        self._reset_session(bar.ts.date(), bar)
        events = self._process_enriched_bar(bar, indicators)
        self.previous_indicators = indicators
        self.previous_bar = bar
        return events
