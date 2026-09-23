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
            rows = self.sources.option_contracts(UNDERLYING, self.option_expiry)
            candidate_set = build_bullish_ce_candidate_set(
                signal_spot=bar.close,
                expiry=self.option_expiry,
                contracts=rows,
                strike_step=self.option_strike_step,
                wings=self.option_candidate_wings,
            )
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
