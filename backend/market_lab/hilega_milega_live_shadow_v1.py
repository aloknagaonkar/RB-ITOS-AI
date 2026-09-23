from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from .domain import IST
from .hilega_milega_historical_replay_v1 import UNDERLYING, aggregate_exact_5m, load_or_fetch_1m
from .hilega_milega_strategy_v1 import (
    HilegaMilegaBullishEngineV1,
    STRATEGY_ID,
    STRATEGY_VERSION,
)
from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1
from .hilega_milega_option_candidate_v1 import build_bullish_ce_candidate_set
from .hilega_milega_option_snapshot_v1 import observe_exact_candidate_market_snapshot
from .hilega_milega_option_shadow_lifecycle_v1 import HilegaMilegaOptionShadowLifecycleV1

MODEL = "HILEGA_MILEGA_LIVE_SHADOW_V1"
OBSERVATION_ONLY = True
EXECUTION_ENABLED = False
PAPER_ORDER_ENABLED = False


def floor_5m(value: datetime) -> datetime:
    local = value.astimezone(IST)
    return local.replace(minute=(local.minute // 5) * 5, second=0, microsecond=0)


def latest_completed_5m_label(now: datetime) -> datetime:
    return floor_5m(now) - timedelta(minutes=5)


def completed_intraday_1m_for_label(candles, completed_label: datetime):
    """Return only 1m rows that belong to bars at or before completed_label.

    The Upstox intraday endpoint may include the currently-forming 5m slot.
    Historical aggregation is intentionally strict and rejects partial slots,
    so live code must remove that causal tail before exact 5m aggregation.
    """
    cutoff = completed_label.astimezone(IST) + timedelta(minutes=5)
    out = []
    for candle in candles:
        ts = candle.timestamp.astimezone(IST).replace(second=0, microsecond=0)
        if ts < cutoff:
            out.append(candle)
    return out


class HealthJournalV1:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, payload: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")


class HilegaMilegaLiveShadowCoordinatorV1:
    """Observation-only live runner for the canonical Hilega-Milega engine.

    Causality:
    * a 5m bar labelled HH:MM is processed only after HH:MM+5 has completed;
    * 14:55 cutoff is a separate open-time event and does not feed a partial
      14:55 candle into the indicator engine;
    * historical/current-day bars used to reconstruct state on restart are
      replayed with auditing disabled, then live auditing is attached.
    """

    def __init__(
        self,
        *,
        market_sources,
        step_audit_path: str | Path = "data/live-observation/hilega-milega-v1/step-audit.jsonl",
        health_path: str | Path = "data/live-observation/hilega-milega-v1/data-health.jsonl",
        cache_root: str | Path = "data/historical-evidence/hilega-milega-underlying-cache-v1",
        warmup_calendar_days: int = 45,
        option_expiry: date | None = None,
        option_candidate_wings: int = 2,
        option_strike_step: float = 50.0,
    ) -> None:
        self.sources = market_sources
        self.step_audit = ShadowStepAuditStoreV1(step_audit_path)
        self.health = HealthJournalV1(health_path)
        self.cache_root = Path(cache_root)
        self.warmup_calendar_days = int(warmup_calendar_days)
        self.option_expiry = option_expiry
        self.option_candidate_wings = int(option_candidate_wings)
        self.option_strike_step = float(option_strike_step)
        self.strategy = HilegaMilegaBullishEngineV1(audit_store=None)
        self._bootstrapped_date: date | None = None
        self._last_bar_ts: datetime | None = None
        self._cutoff_done_date: date | None = None
        self.option_shadow = HilegaMilegaOptionShadowLifecycleV1()
        self._option_shadow_last_update_minute: datetime | None = None
        # Pending exits are independent of the next strategy entry; never
        # allow a new signal to overwrite an unresolved five-strike exit.
        self._pending_option_exits: dict[str, HilegaMilegaOptionShadowLifecycleV1] = {}

    def _health(self, *, now: datetime, status: str, **payload: Any) -> None:
        self.health.append({
            "model": MODEL,
            "strategy_id": STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION,
            "timestamp": now.astimezone(IST).isoformat(),
            "status": status,
            "observation_only": True,
            "execution_enabled": False,
            "paper_order_enabled": False,
            **payload,
        })

    def _audit_runtime(self, now: datetime, stage: str, status: str, payload: dict[str, Any]) -> None:
        self.step_audit.append(
            event_time=now.astimezone(IST),
            checkpoint=None,
            stage=stage,
            status=status,
            payload={
                "strategy_id": STRATEGY_ID,
                "strategy_version": STRATEGY_VERSION,
                **payload,
            },
        )

    def bootstrap(self, now: datetime) -> dict[str, Any]:
        now = now.astimezone(IST)
        session_date = now.date()
        if self._bootstrapped_date == session_date:
            return {"status": "ALREADY_BOOTSTRAPPED", "session_date": session_date.isoformat()}

        # New object ensures a restart reconstructs solely from market history.
        self.strategy = HilegaMilegaBullishEngineV1(audit_store=None)
        bars_replayed = 0
        sessions_loaded = 0
        start = session_date - timedelta(days=self.warmup_calendar_days)
        d = start
        while d < session_date:
            candles = load_or_fetch_1m(
                self.sources,
                underlying=UNDERLYING,
                session_date=d,
                cache_root=self.cache_root,
                refresh_cache=False,
            )
            if candles:
                bars = aggregate_exact_5m(candles, d)
                for bar in bars:
                    self.strategy.on_bar(bar)
                bars_replayed += len(bars)
                sessions_loaded += 1
            d += timedelta(days=1)

        current = self.sources.nifty_intraday_1m(now=now)
        completed_label = latest_completed_5m_label(now)
        completed_current = completed_intraday_1m_for_label(current, completed_label)
        current_bars = aggregate_exact_5m(completed_current, session_date)
        for bar in current_bars:
            if bar.ts <= completed_label:
                self.strategy.on_bar(bar)
                self._last_bar_ts = bar.ts
                bars_replayed += 1

        # Bootstrap history is intentionally not written into the live audit.
        self.strategy.audit_store = self.step_audit
        self._bootstrapped_date = session_date
        self._restore_pending_option_exits(now)
        self._restore_option_shadow(now)
        if self.strategy.session.session_locked:
            self._cutoff_done_date = session_date

        self._audit_runtime(now, "LIVE_BOOTSTRAP", "PASS", {
            "session_date": session_date.isoformat(),
            "warmup_calendar_days": self.warmup_calendar_days,
            "historical_sessions_loaded": sessions_loaded,
            "bars_replayed": bars_replayed,
            "last_completed_bar": self._last_bar_ts.isoformat() if self._last_bar_ts else None,
            "reconstructed_state": self.strategy.session.name,
        })
        self._health(now=now, status="BOOTSTRAPPED", bars_replayed=bars_replayed, reconstructed_state=self.strategy.session.name)
        return {"status": "PASS", "bars_replayed": bars_replayed, "state": self.strategy.session.name}

    @staticmethod
    def _minute_open(candles, target: datetime) -> float | None:
        matches = [c for c in candles if c.timestamp.astimezone(IST).replace(second=0, microsecond=0) == target]
        if len(matches) != 1:
            return None
        return float(matches[0].open)

    def _build_candidate_set_for_signal(self, signal_spot: float):
        if self.option_expiry is None:
            return None
        rows = self.sources.option_contracts(UNDERLYING, self.option_expiry)
        return build_bullish_ce_candidate_set(
            signal_spot=signal_spot,
            expiry=self.option_expiry,
            contracts=rows,
            strike_step=self.option_strike_step,
            wings=self.option_candidate_wings,
        )

    @staticmethod
    def _latest_completed_option_minute(now: datetime) -> datetime:
        local = now.astimezone(IST).replace(second=0, microsecond=0)
        return local - timedelta(minutes=1)

    def _restore_pending_option_exits(self, now: datetime) -> None:
        """Recover pending exits from verified append-only audit, not candle inference.

        Keep every signal independent. Terminal CLOSED rows suppress restoration.
        This method never rewrites the historic audit trail.
        """
        ok, issue = self.step_audit.verify_chain()
        if not ok:
            self._health(now=now, status="AUDIT_CHAIN_INVALID_PENDING_RESTORE_BLOCKED", issue=issue)
            return
        latest: dict[str, dict] = {}
        stages = {
            "OPTION_SHADOW_LIFECYCLE_START", "OPTION_SHADOW_LIFECYCLE_RESTORE",
            "OPTION_SHADOW_LIFECYCLE_ENTRY_RETRY", "OPTION_SHADOW_LIFECYCLE_UPDATE",
            "OPTION_SHADOW_LIFECYCLE_EXIT", "OPTION_SHADOW_LIFECYCLE_EXIT_RETRY",
        }
        for row in self.step_audit.read_all():
            if row.get("stage") not in stages:
                continue
            payload = row.get("payload") or {}
            signal = payload.get("signal_bar")
            if signal and signal.startswith(now.date().isoformat()):
                latest[signal] = payload
        for signal, payload in latest.items():
            if payload.get("status") != "PENDING_EXACT_EXIT":
                continue
            try:
                tracker = HilegaMilegaOptionShadowLifecycleV1.from_audited_active_snapshot(payload)
                self._pending_option_exits[signal] = tracker
                self._audit_runtime(now, "OPTION_SHADOW_PENDING_EXIT_RESTORE", "PASS", tracker.snapshot.payload())
            except (ValueError, KeyError, TypeError) as exc:
                self._audit_runtime(now, "OPTION_SHADOW_PENDING_EXIT_RESTORE", "FAILED", {
                    "signal_bar": signal, "reason": str(exc), "order_created": False,
                })

    def _retry_pending_option_exits(self, now: datetime) -> None:
        for signal, tracker in list(self._pending_option_exits.items()):
            try:
                previous_issue = tracker.snapshot.issue if tracker.snapshot else None
                snap = tracker.retry_pending_exit(option_minutes=self.sources.option_intraday_1m)
                if snap is None:
                    continue
                # Append on resolution or changed evidence only. Repeated exact
                # minute polling must not masquerade as new transitions.
                if snap.status == "CLOSED" or snap.issue != previous_issue:
                    self._audit_runtime(now, "OPTION_SHADOW_LIFECYCLE_EXIT_RETRY", snap.status, snap.payload())
                if snap.status == "CLOSED":
                    del self._pending_option_exits[signal]
            except Exception as exc:
                self._audit_runtime(now, "OPTION_SHADOW_LIFECYCLE_EXIT_RETRY", "FAILED", {
                    "signal_bar": signal, "reason": str(exc), "order_created": False,
                })

    def _retry_missing_option_entry(self, now: datetime) -> None:
        snap = self.option_shadow.snapshot
        if (snap is None or snap.status != "INCOMPLETE" or
                not self.strategy.session.active or
                self.option_shadow._candidate_set is None):
            return
        if self.strategy.session.entry_time is None or self.strategy.session.entry_time.isoformat() != snap.signal_bar:
            return
        # Causal: exact entry minute must already be complete before recovery.
        if self._latest_completed_option_minute(now) < datetime.fromisoformat(snap.signal_boundary):
            return
        try:
            retried = self.option_shadow.retry_missing_entry(
                option_minutes=self.sources.option_intraday_1m)
            self._audit_runtime(now, "OPTION_SHADOW_LIFECYCLE_ENTRY_RETRY", retried.status, retried.payload())
        except Exception as exc:
            self._audit_runtime(now, "OPTION_SHADOW_LIFECYCLE_ENTRY_RETRY", "FAILED", {
                "signal_bar": snap.signal_bar, "reason": str(exc), "order_created": False,
            })

    def _restore_option_shadow(self, now: datetime) -> None:
        if not self.strategy.session.active:
            return
        if self.option_expiry is None:
            self._audit_runtime(now, "OPTION_SHADOW_LIFECYCLE_RESTORE", "NOT_CONFIGURED", {
                "reason": "HILEGA_MILEGA_OPTION_EXPIRY_NOT_CONFIGURED",
                "order_created": False,
                "execution_enabled": False,
                "paper_order_enabled": False,
            })
            return
        if self.strategy.session.entry_time is None or self.strategy.session.entry_price is None:
            self._audit_runtime(now, "OPTION_SHADOW_LIFECYCLE_RESTORE", "FAILED", {
                "reason": "ACTIVE_STRATEGY_ENTRY_IDENTITY_MISSING",
                "order_created": False,
                "execution_enabled": False,
                "paper_order_enabled": False,
            })
            return
        try:
            candidate_set = self._build_candidate_set_for_signal(self.strategy.session.entry_price)
            if candidate_set is None:
                return
            snap = self.option_shadow.start(
                signal_bar_ts=self.strategy.session.entry_time,
                signal_spot=self.strategy.session.entry_price,
                source=self.strategy.session.source,
                candidate_set=candidate_set,
                option_minutes=self.sources.option_intraday_1m,
            )
            status = "PASS" if snap.active else snap.status
            if snap.active:
                updated = self.option_shadow.update(
                    through_completed_minute=self._latest_completed_option_minute(now),
                    option_minutes=self.sources.option_intraday_1m,
                )
                if updated is not None and updated.status == "ACTIVE":
                    snap = updated
            self._option_shadow_last_update_minute = (
                datetime.fromisoformat(snap.latest_completed_minute).astimezone(IST)
                if snap.latest_completed_minute else None
            )
            self._audit_runtime(now, "OPTION_SHADOW_LIFECYCLE_RESTORE", status, snap.payload())
        except Exception as exc:
            self._audit_runtime(now, "OPTION_SHADOW_LIFECYCLE_RESTORE", "FAILED", {
                "error_type": type(exc).__name__,
                "error": str(exc),
                "order_created": False,
                "execution_enabled": False,
                "paper_order_enabled": False,
            })

    def _update_option_shadow(self, now: datetime) -> None:
        self._retry_missing_option_entry(now)
        if not self.option_shadow.active:
            return
        through = self._latest_completed_option_minute(now)
        if self._option_shadow_last_update_minute is not None and through <= self._option_shadow_last_update_minute:
            return
        try:
            snap = self.option_shadow.update(
                through_completed_minute=through,
                option_minutes=self.sources.option_intraday_1m,
            )
            if snap is None:
                return
            status = "PASS" if snap.status == "ACTIVE" else snap.status
            self._audit_runtime(now, "OPTION_SHADOW_LIFECYCLE_UPDATE", status, snap.payload())
            if snap.status == "ACTIVE":
                self._option_shadow_last_update_minute = through
        except Exception as exc:
            self._audit_runtime(now, "OPTION_SHADOW_LIFECYCLE_UPDATE", "FAILED", {
                "through_completed_minute": through.isoformat(),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "order_created": False,
                "execution_enabled": False,
                "paper_order_enabled": False,
            })
            # Do not advance the success watermark on a failed fetch; a later
            # poll may receive the missing exact minute and can retry causally.

    def _close_option_shadow(self, now: datetime, *, exit_boundary: datetime, exit_reason: str) -> None:
        if not self.option_shadow.active:
            return
        try:
            snap = self.option_shadow.close(
                exit_boundary=exit_boundary,
                exit_reason=exit_reason,
                option_minutes=self.sources.option_intraday_1m,
            )
            if snap is None:
                return
            status = "PASS" if snap.status == "CLOSED" else snap.status
            self._audit_runtime(now, "OPTION_SHADOW_LIFECYCLE_EXIT", status, snap.payload())
            if snap.status == "PENDING_EXACT_EXIT":
                self._pending_option_exits[snap.signal_bar] = self.option_shadow
                self.option_shadow = HilegaMilegaOptionShadowLifecycleV1()
                self._option_shadow_last_update_minute = None
        except Exception as exc:
            self._audit_runtime(now, "OPTION_SHADOW_LIFECYCLE_EXIT", "FAILED", {
                "exit_boundary": exit_boundary.isoformat(),
                "exit_reason": exit_reason,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "order_created": False,
                "execution_enabled": False,
                "paper_order_enabled": False,
            })

    def process_cutoff(self, now: datetime, *, intraday=None) -> list:
        now = now.astimezone(IST)
        if now.time() < time(14, 55) or self._cutoff_done_date == now.date():
            return []
        intraday = intraday if intraday is not None else self.sources.nifty_intraday_1m(now=now)
        cutoff_ts = datetime.combine(now.date(), time(14, 55), tzinfo=IST)
        open_price = self._minute_open(intraday, cutoff_ts)
        if open_price is None:
            self._audit_runtime(now, "SESSION_CUTOFF_SOURCE", "WAITING", {"expected_minute": cutoff_ts.isoformat()})
            return []
        events = self.strategy.on_session_cutoff(cutoff_ts, open_price)
        if any(e.event_type == "SESSION_CUTOFF_EXIT_1455_OPEN" for e in events):
            self._close_option_shadow(now, exit_boundary=cutoff_ts, exit_reason="SESSION_CUTOFF_14_55_OPEN")
        self._cutoff_done_date = now.date()
        self._audit_runtime(now, "SESSION_CUTOFF_SOURCE", "PROCESSED", {
            "cutoff_timestamp": cutoff_ts.isoformat(),
            "cutoff_open": open_price,
            "events": [e.event_type for e in events],
        })
        return events

    def _observe_option_candidates(self, now: datetime, bar, events: list) -> None:
        entry_events = [e for e in events if e.event_type.startswith("ENTRY_")]
        if not entry_events:
            return
        if self.option_expiry is None:
            self._audit_runtime(now, "OPTION_CANDIDATE_SET", "NOT_CONFIGURED", {
                "signal_bar": bar.ts.isoformat(),
                "signal_spot": bar.close,
                "reason": "HILEGA_MILEGA_OPTION_EXPIRY_NOT_CONFIGURED",
                "selection_policy": "UNDECIDED_CANDIDATE_SET_ONLY",
                "selected_instrument_key": None,
                "order_created": False,
            })
            return
        try:
            candidate_set = self._build_candidate_set_for_signal(bar.close)
            if candidate_set is None:
                return
            status = "PASS" if candidate_set.status == "AVAILABLE" else "INCOMPLETE"
            payload = candidate_set.payload()
            payload.update({
                "signal_bar": bar.ts.isoformat(),
                "entry_events": [e.event_type for e in entry_events],
                "order_created": False,
                "execution_enabled": False,
                "paper_order_enabled": False,
            })
            self._audit_runtime(now, "OPTION_CANDIDATE_SET", status, payload)
            if candidate_set.status == "AVAILABLE":
                try:
                    snapshot = observe_exact_candidate_market_snapshot(
                        signal_bar_ts=bar.ts,
                        candidate_set=candidate_set,
                        option_minutes=self.sources.option_intraday_1m,
                    )
                    snapshot_payload = snapshot.payload()
                    snapshot_payload.update({
                        "entry_events": [e.event_type for e in entry_events],
                        "order_created": False,
                        "execution_enabled": False,
                        "paper_order_enabled": False,
                    })
                    snapshot_status = "PASS" if snapshot.status == "AVAILABLE" else snapshot.status
                    self._audit_runtime(now, "OPTION_CANDIDATE_MARKET_SNAPSHOT", snapshot_status, snapshot_payload)
                except Exception as exc:
                    self._audit_runtime(now, "OPTION_CANDIDATE_MARKET_SNAPSHOT", "FAILED", {
                        "signal_bar": bar.ts.isoformat(),
                        "signal_spot": bar.close,
                        "expiry": self.option_expiry.isoformat(),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "selected_instrument_key": None,
                        "order_created": False,
                        "execution_enabled": False,
                        "paper_order_enabled": False,
                    })
                try:
                    source = entry_events[0].source if entry_events else None
                    lifecycle = self.option_shadow.start(
                        signal_bar_ts=bar.ts,
                        signal_spot=bar.close,
                        source=source,
                        candidate_set=candidate_set,
                        option_minutes=self.sources.option_intraday_1m,
                    )
                    lifecycle_status = "PASS" if lifecycle.active else lifecycle.status
                    self._audit_runtime(now, "OPTION_SHADOW_LIFECYCLE_START", lifecycle_status, lifecycle.payload())
                    self._option_shadow_last_update_minute = None
                except Exception as exc:
                    self._audit_runtime(now, "OPTION_SHADOW_LIFECYCLE_START", "FAILED", {
                        "signal_bar": bar.ts.isoformat(),
                        "signal_spot": bar.close,
                        "expiry": self.option_expiry.isoformat(),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "order_created": False,
                        "execution_enabled": False,
                        "paper_order_enabled": False,
                    })
        except Exception as exc:
            self._audit_runtime(now, "OPTION_CANDIDATE_SET", "FAILED", {
                "signal_bar": bar.ts.isoformat(),
                "signal_spot": bar.close,
                "expiry": self.option_expiry.isoformat(),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "selected_instrument_key": None,
                "order_created": False,
            })

    def process(self, now: datetime) -> dict[str, Any]:
        now = now.astimezone(IST)
        self.bootstrap(now)
        intraday = self.sources.nifty_intraday_1m(now=now)
        cutoff_events = self.process_cutoff(now, intraday=intraday)
        self._retry_pending_option_exits(now)
        self._update_option_shadow(now)

        target = latest_completed_5m_label(now)
        if target.date() != now.date() or target.time() < time(9, 15):
            return {"status": "WAITING_FOR_SESSION", "cutoff_events": [e.event_type for e in cutoff_events]}
        if self._last_bar_ts is not None and target <= self._last_bar_ts:
            return {"status": "NO_NEW_COMPLETED_BAR", "last_bar": self._last_bar_ts.isoformat(), "cutoff_events": [e.event_type for e in cutoff_events]}

        try:
            completed_intraday = completed_intraday_1m_for_label(intraday, target)
            bars = aggregate_exact_5m(completed_intraday, now.date())
        except Exception as exc:
            self._audit_runtime(now, "UNDERLYING_5M_BUILD", "FAILED", {"error_type": type(exc).__name__, "error": str(exc)})
            self._health(now=now, status="UNDERLYING_5M_UNAVAILABLE", error=str(exc))
            return {"status": "UNDERLYING_5M_UNAVAILABLE", "error": str(exc)}

        matches = [b for b in bars if b.ts == target]
        if len(matches) != 1:
            self._audit_runtime(now, "UNDERLYING_5M_BUILD", "WAITING", {"expected_bar": target.isoformat(), "match_count": len(matches)})
            return {"status": "WAITING_FOR_EXACT_COMPLETED_5M", "expected_bar": target.isoformat()}

        bar = matches[0]
        events = self.strategy.on_bar(bar)
        for event in events:
            if event.event_type == "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21":
                if self.option_shadow.snapshot is not None and self.option_shadow.snapshot.status == "INCOMPLETE":
                    self._audit_runtime(now, "OPTION_SHADOW_ENTRY_UNAVAILABLE_AT_EXIT", "INCOMPLETE", {
                        "signal_bar": self.option_shadow.snapshot.signal_bar,
                        "exit_boundary": (bar.ts + timedelta(minutes=5)).isoformat(),
                        "reason": "EXACT_ENTRY_NOT_OBSERVED_BEFORE_EXIT",
                        "order_created": False,
                    })
                self._close_option_shadow(
                    now,
                    exit_boundary=bar.ts + timedelta(minutes=5),
                    exit_reason=event.exit_reason or "RSI_CROSS_BELOW_WMA21",
                )
        self._observe_option_candidates(now, bar, events)
        self._last_bar_ts = bar.ts
        self._audit_runtime(now, "UNDERLYING_5M_BUILD", "PROCESSED", {
            "bar_timestamp": bar.ts.isoformat(),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "events": [e.event_type for e in events],
            "state": self.strategy.session.name,
        })
        self._health(now=now, status="PROCESSED", bar_timestamp=bar.ts.isoformat(), state=self.strategy.session.name, events=[e.event_type for e in events])
        return {
            "status": "PROCESSED",
            "bar_timestamp": bar.ts.isoformat(),
            "state": self.strategy.session.name,
            "events": [e.event_type for e in events],
            "cutoff_events": [e.event_type for e in cutoff_events],
        }
