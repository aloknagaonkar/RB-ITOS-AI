from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from .domain import IST
from .hilega_directional_coordinator_v1 import (
    BEARISH_ENTRY_EVENTS,
    BEARISH_EXIT_EVENTS,
    BULLISH_ENTRY_EVENTS,
    BULLISH_EXIT_EVENTS,
    DirectionalDecision,
    HilegaDirectionalCoordinatorV1,
)
from .hilega_milega_bearish_strategy_v1 import BearishSessionState
from .hilega_milega_historical_replay_v1 import UNDERLYING, aggregate_exact_5m, load_or_fetch_1m
from .hilega_milega_live_shadow_v1 import (
    completed_intraday_1m_for_label,
    latest_completed_5m_label,
)
from .hilega_milega_option_candidate_v1 import build_bullish_ce_candidate_set
from .hilega_milega_option_shadow_lifecycle_v1 import HilegaMilegaOptionShadowLifecycleV1
from .hilega_milega_pe_option_candidate_v1 import build_bearish_pe_candidate_set
from .hilega_milega_pe_option_shadow_lifecycle_v1 import HilegaMilegaPEOptionShadowLifecycleV1
from .hilega_milega_strategy_v1 import SessionState
from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1

MODEL = "HILEGA_DIRECTIONAL_LIVE_SHADOW_V1"
STRATEGY_ID = "HILEGA_DIRECTIONAL_SHADOW_V1"
STRATEGY_VERSION = "1.0.0"
OBSERVATION_ONLY = True
EXECUTION_ENABLED = False
PAPER_ORDER_ENABLED = False
OPTION_SELECTION_ENABLED = False


class _HealthJournal:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, payload: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")


class HilegaDirectionalLiveShadowCoordinatorV1:
    """Observation-only live directional Hilega shadow.

    The frozen bullish engine and candidate bearish engine remain independent.
    HilegaDirectionalCoordinatorV1 is the only authority allowed to accept an
    entry. Accepted bullish entries start CE ATM±2 shadow; accepted bearish
    entries start PE ATM±2 shadow. Suppressed entries never start option state.
    """

    def __init__(
        self,
        *,
        market_sources,
        option_expiry: date | None,
        step_audit_path: str | Path = "data/live-observation/hilega-directional-v1/step-audit.jsonl",
        health_path: str | Path = "data/live-observation/hilega-directional-v1/data-health.jsonl",
        cache_root: str | Path = "data/historical-evidence/hilega-milega-underlying-cache-v1",
        warmup_calendar_days: int = 45,
        option_candidate_wings: int = 2,
        option_strike_step: float = 50.0,
    ) -> None:
        self.sources = market_sources
        self.option_expiry = option_expiry
        self.step_audit = ShadowStepAuditStoreV1(step_audit_path)
        self.health = _HealthJournal(health_path)
        self.cache_root = Path(cache_root)
        self.warmup_calendar_days = int(warmup_calendar_days)
        self.option_candidate_wings = int(option_candidate_wings)
        self.option_strike_step = float(option_strike_step)

        self.directional = HilegaDirectionalCoordinatorV1()
        self.ce_shadow = HilegaMilegaOptionShadowLifecycleV1()
        self.pe_shadow = HilegaMilegaPEOptionShadowLifecycleV1()
        self._pending_ce_exits: dict[str, HilegaMilegaOptionShadowLifecycleV1] = {}
        self._pending_pe_exits: dict[str, HilegaMilegaPEOptionShadowLifecycleV1] = {}
        self._ce_last_update: datetime | None = None
        self._pe_last_update: datetime | None = None
        self._bootstrapped_date: date | None = None
        self._last_bar_ts: datetime | None = None
        self._cutoff_done_date: date | None = None

    def _safe(self) -> dict[str, Any]:
        return {
            "model": MODEL,
            "strategy_id": STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION,
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
            "option_selection_enabled": False,
            "quantity": None,
            "rupee_pnl_enabled": False,
        }

    def _audit(self, now: datetime, stage: str, status: str, payload: dict[str, Any], checkpoint=None) -> None:
        self.step_audit.append(
            event_time=now.astimezone(IST),
            checkpoint=checkpoint,
            stage=stage,
            status=status,
            payload={**self._safe(), **payload},
        )

    def _health(self, now: datetime, status: str, **payload: Any) -> None:
        self.health.append({**self._safe(), "timestamp": now.astimezone(IST).isoformat(), "status": status, **payload})

    @staticmethod
    def _minute_open(candles, target: datetime) -> float | None:
        target = target.astimezone(IST).replace(second=0, microsecond=0)
        rows = [c for c in candles if c.timestamp.astimezone(IST).replace(second=0, microsecond=0) == target]
        if len(rows) != 1:
            return None
        return float(rows[0].open)

    @staticmethod
    def _latest_completed_option_minute(now: datetime) -> datetime:
        local = now.astimezone(IST).replace(second=0, microsecond=0)
        return local - timedelta(minutes=1)

    def _candidate_set(self, direction: str, spot: float):
        if self.option_expiry is None:
            return None
        contracts = self.sources.option_contracts(UNDERLYING, self.option_expiry)
        common = dict(
            signal_spot=float(spot),
            expiry=self.option_expiry,
            contracts=contracts,
            strike_step=self.option_strike_step,
            wings=self.option_candidate_wings,
        )
        if direction == "BULLISH":
            return build_bullish_ce_candidate_set(**common)
        return build_bearish_pe_candidate_set(**common)

    def _start_option(self, *, direction: str, now: datetime, bar, event, audit: bool) -> None:
        if self.option_expiry is None:
            if audit:
                self._audit(now, f"{direction}_OPTION_SHADOW_START", "NOT_CONFIGURED", {
                    "signal_bar": bar.ts.isoformat(), "reason": "HILEGA_MILEGA_OPTION_EXPIRY_NOT_CONFIGURED"
                }, checkpoint=bar.ts)
            return
        try:
            candidate_set = self._candidate_set(direction, bar.close)
            if candidate_set is None:
                return
            lifecycle = self.ce_shadow if direction == "BULLISH" else self.pe_shadow
            if lifecycle.active or lifecycle.pending_exit:
                if audit:
                    self._audit(now, f"{direction}_OPTION_SHADOW_START", "BLOCKED", {
                        "signal_bar": bar.ts.isoformat(), "reason": "OPTION_LIFECYCLE_ALREADY_OPEN"
                    }, checkpoint=bar.ts)
                return
            snap = lifecycle.start(
                signal_bar_ts=bar.ts,
                signal_spot=bar.close,
                source=event.source,
                candidate_set=candidate_set,
                option_minutes=self.sources.option_intraday_1m,
            )
            if direction == "BULLISH":
                self._ce_last_update = None
            else:
                self._pe_last_update = None
            if audit:
                self._audit(now, f"{direction}_OPTION_SHADOW_START", "PASS" if snap.active else snap.status,
                            snap.payload(), checkpoint=bar.ts)
        except Exception as exc:
            if audit:
                self._audit(now, f"{direction}_OPTION_SHADOW_START", "FAILED", {
                    "signal_bar": bar.ts.isoformat(), "error_type": type(exc).__name__, "error": str(exc)
                }, checkpoint=bar.ts)

    def _close_option(self, *, direction: str, now: datetime, exit_boundary: datetime, exit_reason: str, audit: bool) -> None:
        lifecycle = self.ce_shadow if direction == "BULLISH" else self.pe_shadow
        if not lifecycle.active and not lifecycle.pending_exit:
            return
        try:
            snap = lifecycle.close(
                exit_boundary=exit_boundary,
                exit_reason=exit_reason,
                option_minutes=self.sources.option_intraday_1m,
            )
            if snap is None:
                return
            if audit:
                self._audit(now, f"{direction}_OPTION_SHADOW_EXIT",
                            "PASS" if snap.status == "CLOSED" else snap.status, snap.payload())
            if snap.status == "PENDING_EXACT_EXIT":
                if direction == "BULLISH":
                    self._pending_ce_exits[snap.signal_bar] = lifecycle
                    self.ce_shadow = HilegaMilegaOptionShadowLifecycleV1()
                    self._ce_last_update = None
                else:
                    self._pending_pe_exits[snap.signal_bar] = lifecycle
                    self.pe_shadow = HilegaMilegaPEOptionShadowLifecycleV1()
                    self._pe_last_update = None
        except Exception as exc:
            if audit:
                self._audit(now, f"{direction}_OPTION_SHADOW_EXIT", "FAILED", {
                    "exit_boundary": exit_boundary.isoformat(), "error_type": type(exc).__name__, "error": str(exc)
                })

    def _retry_pending(self, now: datetime) -> None:
        for direction, store in (("BULLISH", self._pending_ce_exits), ("BEARISH", self._pending_pe_exits)):
            for key, lifecycle in list(store.items()):
                try:
                    snap = lifecycle.retry_pending_exit(option_minutes=self.sources.option_intraday_1m)
                    if snap is not None:
                        self._audit(now, f"{direction}_OPTION_SHADOW_EXIT_RETRY", snap.status, snap.payload())
                        if snap.status == "CLOSED":
                            del store[key]
                except Exception as exc:
                    self._audit(now, f"{direction}_OPTION_SHADOW_EXIT_RETRY", "FAILED", {
                        "signal_bar": key, "error_type": type(exc).__name__, "error": str(exc)
                    })

    def _update_one(self, direction: str, now: datetime) -> None:
        lifecycle = self.ce_shadow if direction == "BULLISH" else self.pe_shadow
        if not lifecycle.active:
            return
        through = self._latest_completed_option_minute(now)
        last = self._ce_last_update if direction == "BULLISH" else self._pe_last_update
        if last is not None and through <= last:
            return
        try:
            snap = lifecycle.update(through_completed_minute=through, option_minutes=self.sources.option_intraday_1m)
            if snap is not None:
                self._audit(now, f"{direction}_OPTION_SHADOW_UPDATE", snap.status, snap.payload())
                if direction == "BULLISH":
                    self._ce_last_update = through
                else:
                    self._pe_last_update = through
        except Exception as exc:
            self._audit(now, f"{direction}_OPTION_SHADOW_UPDATE", "FAILED", {
                "through": through.isoformat(), "error_type": type(exc).__name__, "error": str(exc)
            })

    def _update_options(self, now: datetime) -> None:
        self._update_one("BULLISH", now)
        self._update_one("BEARISH", now)

    def _accepted_types(self, decision: DirectionalDecision) -> set[str]:
        return {e.event_type for e in decision.accepted_events}

    def _handle_decision(self, *, now: datetime, bar, decision: DirectionalDecision, audit: bool) -> None:
        accepted = self._accepted_types(decision)
        if audit:
            self._audit(now, "DIRECTIONAL_DECISION", "PROCESSED", {
                "bar_timestamp": bar.ts.isoformat(),
                "trade_owner_before": decision.trade_owner_before,
                "trade_owner_after": decision.trade_owner_after,
                "bullish_state": decision.bullish_state,
                "bearish_state": decision.bearish_state,
                "bullish_armed": decision.bullish_armed,
                "bearish_armed": decision.bearish_armed,
                "accepted_events": [e.event_type for e in decision.accepted_events],
                "suppressed_events": [e.event_type for e in decision.suppressed_events],
                "note": decision.note,
            }, checkpoint=bar.ts)

        for e in decision.accepted_events:
            if e.event_type in BULLISH_EXIT_EVENTS:
                self._close_option(direction="BULLISH", now=now, exit_boundary=bar.ts + timedelta(minutes=5),
                                   exit_reason=e.exit_reason or e.event_type, audit=audit)
            elif e.event_type in BEARISH_EXIT_EVENTS:
                self._close_option(direction="BEARISH", now=now, exit_boundary=bar.ts + timedelta(minutes=5),
                                   exit_reason=e.exit_reason or e.event_type, audit=audit)

        if bar.ts.time() >= time(14, 50):
            if audit and (accepted & (BULLISH_ENTRY_EVENTS | BEARISH_ENTRY_EVENTS)):
                self._audit(now, "OPTION_ENTRY_CUTOFF_GUARD", "BLOCKED", {
                    "signal_bar": bar.ts.isoformat(), "reason": "NO_NEW_OPTION_ENTRIES_AT_1455"
                }, checkpoint=bar.ts)
            return

        for e in decision.accepted_events:
            if e.event_type in BULLISH_ENTRY_EVENTS:
                self._start_option(direction="BULLISH", now=now, bar=bar, event=e, audit=audit)
            elif e.event_type in BEARISH_ENTRY_EVENTS:
                self._start_option(direction="BEARISH", now=now, bar=bar, event=e, audit=audit)

    def bootstrap(self, now: datetime) -> dict[str, Any]:
        now = now.astimezone(IST)
        session_date = now.date()
        if self._bootstrapped_date == session_date:
            return {"status": "ALREADY_BOOTSTRAPPED", "session_date": session_date.isoformat()}

        self.directional = HilegaDirectionalCoordinatorV1()
        self.ce_shadow = HilegaMilegaOptionShadowLifecycleV1()
        self.pe_shadow = HilegaMilegaPEOptionShadowLifecycleV1()
        self._pending_ce_exits.clear()
        self._pending_pe_exits.clear()
        self._ce_last_update = self._pe_last_update = None
        self._last_bar_ts = None
        self._cutoff_done_date = None

        sessions_loaded = 0
        bars_replayed = 0
        d = session_date - timedelta(days=self.warmup_calendar_days)
        while d < session_date:
            if hasattr(self.sources, "warmup_candles"):
                candles = self.sources.warmup_candles(d, self.cache_root)
            else:
                candles = load_or_fetch_1m(self.sources, underlying=UNDERLYING, session_date=d,
                                           cache_root=self.cache_root, refresh_cache=False)
            if candles:
                for bar in aggregate_exact_5m(candles, d):
                    self.directional.on_bar(bar)
                    bars_replayed += 1
                sessions_loaded += 1
            d += timedelta(days=1)

        # Keep warmed indicator engines but reset cross-session state.
        self.directional.bullish.session = SessionState(session_date=session_date)
        self.directional.bullish.previous_indicators = None
        self.directional.bullish.previous_bar = None
        self.directional.bearish.session = BearishSessionState(session_date=session_date)
        self.directional.bearish.previous_indicators = None
        self.directional.bearish.previous_bar = None
        self.directional.trade_owner = "NONE"
        self.directional.session_date = session_date

        current = self.sources.nifty_intraday_1m(now=now)
        completed_label = latest_completed_5m_label(now)
        completed_current = completed_intraday_1m_for_label(current, completed_label)
        current_bars = aggregate_exact_5m(completed_current, session_date)
        for bar in current_bars:
            if bar.ts <= completed_label:
                decision = self.directional.on_bar(bar)
                self._handle_decision(now=now, bar=bar, decision=decision, audit=False)
                self._last_bar_ts = bar.ts
                bars_replayed += 1

        self._bootstrapped_date = session_date
        self._update_options(now)
        if self.directional.bullish.session.session_locked or self.directional.bearish.session.session_locked:
            self._cutoff_done_date = session_date
        self._audit(now, "DIRECTIONAL_LIVE_BOOTSTRAP", "PASS", {
            "session_date": session_date.isoformat(),
            "historical_sessions_loaded": sessions_loaded,
            "bars_replayed": bars_replayed,
            "last_completed_bar": self._last_bar_ts.isoformat() if self._last_bar_ts else None,
            "trade_owner": self.directional.trade_owner,
            "bullish_state": self.directional.bullish.session.name,
            "bearish_state": self.directional.bearish.session.name,
            "ce_shadow_status": self.ce_shadow.snapshot.status if self.ce_shadow.snapshot else None,
            "pe_shadow_status": self.pe_shadow.snapshot.status if self.pe_shadow.snapshot else None,
        })
        return {"status": "BOOTSTRAPPED", "session_date": session_date.isoformat(), "trade_owner": self.directional.trade_owner}

    def process_cutoff(self, now: datetime, *, intraday) -> DirectionalDecision | None:
        now = now.astimezone(IST)
        cutoff_ts = datetime.combine(now.date(), time(14, 55), tzinfo=IST)
        if now < cutoff_ts or self._cutoff_done_date == now.date():
            return None
        open_price = self._minute_open(intraday, cutoff_ts)
        if open_price is None:
            self._audit(now, "DIRECTIONAL_SESSION_CUTOFF", "WAITING", {
                "cutoff_timestamp": cutoff_ts.isoformat(), "reason": "EXACT_1455_OPEN_UNAVAILABLE"
            })
            return None
        decision = self.directional.on_session_cutoff(cutoff_ts, open_price)
        # At cutoff, option exit boundary is the exact 14:55 OPEN itself.
        for e in decision.accepted_events:
            if e.event_type in BULLISH_EXIT_EVENTS:
                self._close_option(direction="BULLISH", now=now, exit_boundary=cutoff_ts,
                                   exit_reason=e.exit_reason or e.event_type, audit=True)
            elif e.event_type in BEARISH_EXIT_EVENTS:
                self._close_option(direction="BEARISH", now=now, exit_boundary=cutoff_ts,
                                   exit_reason=e.exit_reason or e.event_type, audit=True)
        self._cutoff_done_date = now.date()
        self._audit(now, "DIRECTIONAL_SESSION_CUTOFF", "PROCESSED", {
            "cutoff_timestamp": cutoff_ts.isoformat(), "cutoff_open": open_price,
            "trade_owner_before": decision.trade_owner_before,
            "trade_owner_after": decision.trade_owner_after,
            "accepted_events": [e.event_type for e in decision.accepted_events],
            "suppressed_events": [e.event_type for e in decision.suppressed_events],
        })
        return decision

    def _process_completed_target(self, now: datetime, intraday, target: datetime) -> dict[str, Any]:
        if target.date() != now.date() or target.time() < time(9, 15):
            return {"status": "WAITING_FOR_SESSION"}
        if self._last_bar_ts is not None and target <= self._last_bar_ts:
            return {"status": "NO_NEW_COMPLETED_BAR", "last_bar": self._last_bar_ts.isoformat()}
        try:
            completed = completed_intraday_1m_for_label(intraday, target)
            bars = aggregate_exact_5m(completed, now.date())
        except Exception as exc:
            self._audit(now, "DIRECTIONAL_UNDERLYING_5M", "FAILED", {"error_type": type(exc).__name__, "error": str(exc)})
            self._health(now, "UNDERLYING_5M_UNAVAILABLE", error=str(exc))
            return {"status": "UNDERLYING_5M_UNAVAILABLE", "error": str(exc)}
        matches = [b for b in bars if b.ts == target]
        if len(matches) != 1:
            return {"status": "WAITING_FOR_EXACT_COMPLETED_5M", "expected_bar": target.isoformat()}
        bar = matches[0]
        decision = self.directional.on_bar(bar)
        self._handle_decision(now=now, bar=bar, decision=decision, audit=True)
        self._last_bar_ts = bar.ts
        self._health(now, "PROCESSED", bar_timestamp=bar.ts.isoformat(), trade_owner=decision.trade_owner_after,
                     bullish_state=decision.bullish_state, bearish_state=decision.bearish_state,
                     accepted_events=[e.event_type for e in decision.accepted_events],
                     suppressed_events=[e.event_type for e in decision.suppressed_events])
        return {
            "status": "PROCESSED",
            "bar_timestamp": bar.ts.isoformat(),
            "trade_owner": decision.trade_owner_after,
            "accepted_events": [e.event_type for e in decision.accepted_events],
            "suppressed_events": [e.event_type for e in decision.suppressed_events],
        }

    def process(self, now: datetime) -> dict[str, Any]:
        now = now.astimezone(IST)
        self.bootstrap(now)
        intraday = self.sources.nifty_intraday_1m(now=now)
        target = latest_completed_5m_label(now)
        cutoff = datetime.combine(now.date(), time(14, 55), tzinfo=IST)
        if cutoff <= now < cutoff + timedelta(minutes=5) and target.time() == time(14, 50):
            result = self._process_completed_target(now, intraday, target)
            cutoff_decision = self.process_cutoff(now, intraday=intraday)
        else:
            cutoff_decision = self.process_cutoff(now, intraday=intraday)
            result = self._process_completed_target(now, intraday, target)
        self._retry_pending(now)
        self._update_options(now)
        return {**result, "cutoff_processed": cutoff_decision is not None}
