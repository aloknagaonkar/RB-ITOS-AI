from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from time import monotonic

import pandas as pd

from red_bar_lab.execution.automation import RedBarPaperAutomationService
from red_bar_lab.execution.opportunity_engine import OpportunityIntelligenceEngine
from red_bar_lab.execution.paper_engine import RedBarPaperExecutionEngine


@dataclass(frozen=True)
class EMA10TrendSnapshot:
    ready: bool
    close: float | None
    ema10: float | None
    timestamp: str | None
    reason: str


class EMA10OpportunityIntelligenceEngine(OpportunityIntelligenceEngine):
    """Add completed-underlying 5m EMA10 continuation to Opportunity Health."""

    def evaluate(self, **kwargs):
        result = super().evaluate(**kwargs)
        signal = kwargs.get("signal") or {}
        direction = str(signal.get("direction") or "").upper()
        ready = bool(signal.get("_ema10_5m_ready"))
        close = signal.get("_ema10_5m_close")
        ema10 = signal.get("_ema10_5m_value")

        informational_tokens = {
            "OPPORTUNITY_HEALTH_PASS",
            "REWARD_METRICS_INFORMATIONAL_ONLY",
            "REWARD_CONSUMED",
        }
        blockers = [
            item.strip()
            for item in str(result.reason or "").split("|")
            if item.strip() and item.strip() not in informational_tokens
        ]

        if not ready or close is None or ema10 is None:
            blockers.append("EMA10_DATA_UNAVAILABLE")
        else:
            close_value = float(close)
            ema_value = float(ema10)
            if direction == "BEARISH" and close_value > ema_value:
                blockers.append("BEARISH_EMA10_LOST")
            elif direction == "BULLISH" and close_value < ema_value:
                blockers.append("BULLISH_EMA10_LOST")
            elif direction not in {"BULLISH", "BEARISH"}:
                blockers.append("EMA10_DIRECTION_UNKNOWN")

        blockers = list(dict.fromkeys(blockers))
        eligible = not blockers
        return replace(
            result,
            eligible=eligible,
            decision=(
                f"BUY {kwargs['candidate'].contract.option_type}"
                if eligible else "SKIP"
            ),
            reason=(
                "OPPORTUNITY_HEALTH_PASS | EMA10_TREND_VALID | "
                "REWARD_METRICS_INFORMATIONAL_ONLY"
                if eligible else " | ".join(blockers)
            ),
        )


class NoTargetPaperExecutionEngine(RedBarPaperExecutionEngine):
    """Keep hard risk stop while disabling fixed profit targets."""

    def open_long_option(self, **kwargs):
        kwargs["target1_price"] = None
        kwargs["target2_price"] = None
        return super().open_long_option(**kwargs)


class TrendAwareDatabaseProxy:
    """DB proxy adding EMA context and account-wide active-contract deduplication."""

    ACTIVE_QUEUE_STATUSES = {
        "QUALIFIED",
        "APPROVED",
        "PENDING",
        "EXECUTING",
        "ACTIVE",
    }

    def __init__(self, database, trend_provider):
        self._database = database
        self._trend_provider = trend_provider

    def __getattr__(self, name: str):
        return getattr(self._database, name)

    def _enrich(self, row):
        if not row:
            return row
        trend = self._trend_provider()
        enriched = dict(row)
        enriched["_ema10_5m_ready"] = trend.ready
        enriched["_ema10_5m_close"] = trend.close
        enriched["_ema10_5m_value"] = trend.ema10
        enriched["_ema10_5m_timestamp"] = trend.timestamp
        enriched["_ema10_5m_reason"] = trend.reason
        return enriched

    def read_signal_attempts(self, *args, **kwargs):
        return [
            self._enrich(row)
            for row in self._database.read_signal_attempts(*args, **kwargs)
        ]

    def read_signal_attempt_by_id(self, *args, **kwargs):
        return self._enrich(
            self._database.read_signal_attempt_by_id(*args, **kwargs)
        )

    def paper_execution_exists_for_candidate(
        self,
        *,
        signal_id: str,
        account_id: str,
        instrument_token: int,
    ) -> bool:
        """OPEN/PENDING same contract blocks; CLOSED contract can be reconsidered.

        The current signal's own queue row is not treated as its duplicate, so an
        APPROVED queue item can execute. A pending row for another signal still
        blocks stacking the same option contract.
        """
        token = int(instrument_token)
        open_rows = self._database.read_open_paper_execution_orders(account_id)
        if any(
            int(row.get("instrument_token") or 0) == token
            for row in open_rows
        ):
            return True

        try:
            queue_rows = self._database.read_execution_queue(limit=5000)
        except TypeError:
            queue_rows = self._database.read_execution_queue()
        for row in queue_rows or []:
            if int(row.get("instrument_token") or 0) != token:
                continue
            if str(row.get("signal_id") or "") == str(signal_id):
                continue
            if str(row.get("status") or "").upper() in self.ACTIVE_QUEUE_STATUSES:
                return True
        return False


class TrendAwarePaperAutomationService(RedBarPaperAutomationService):
    """Paper automation implementing agreed execution Changes 1-5."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._trend_cache_at = 0.0
        self._trend_cache = EMA10TrendSnapshot(
            False, None, None, None, "NOT_LOADED"
        )
        self._raw_database = self.database
        proxy = TrendAwareDatabaseProxy(
            self._raw_database,
            self._ema10_snapshot,
        )
        self.database = proxy

        old_opportunity = self.opportunity_engine
        self.opportunity_engine = EMA10OpportunityIntelligenceEngine(
            minimum_opportunity_score=old_opportunity.minimum_opportunity_score,
            minimum_extended_candidate_score=(
                old_opportunity.minimum_extended_candidate_score
            ),
            minimum_reward_remaining_pct=(
                old_opportunity.minimum_reward_remaining_pct
            ),
            minimum_liquidity_score=old_opportunity.minimum_liquidity_score,
            minimum_spread_score=old_opportunity.minimum_spread_score,
            minimum_momentum_score=old_opportunity.minimum_momentum_score,
        )

        # PerformanceTradeSelectionEngine is globally updated so R:R is already
        # informational-only. The Committee is also globally updated so payoff
        # metrics have zero execution authority.

        old_engine = self.engine
        self.engine = NoTargetPaperExecutionEngine(
            proxy,
            old_engine.settings,
            account_id=old_engine.account_id,
            initial_capital=old_engine.initial_capital,
            slippage_bps=old_engine.slippage_bps,
        )

    def _ema10_snapshot(self) -> EMA10TrendSnapshot:
        now_mono = monotonic()
        if now_mono - self._trend_cache_at <= 10.0:
            return self._trend_cache
        self._trend_cache = self._load_ema10_snapshot()
        self._trend_cache_at = now_mono
        return self._trend_cache

    def _load_ema10_snapshot(self) -> EMA10TrendSnapshot:
        adapter = self.zerodha
        provider = getattr(adapter, "provider", None)
        underlying_key = getattr(adapter, "underlying_key", None)
        if provider is None or not underlying_key:
            return EMA10TrendSnapshot(
                False,
                None,
                None,
                None,
                "UNDERLYING_CANDLE_PROVIDER_UNAVAILABLE",
            )

        today = date.today()
        frames: list[pd.DataFrame] = []
        try:
            history = provider.historical_candles(
                underlying_key,
                today - timedelta(days=7),
                today - timedelta(days=1),
                interval_minutes=1,
            )
            if history is not None and not history.empty:
                frames.append(history)
        except Exception:
            pass

        try:
            intraday = provider.intraday_candles(
                underlying_key,
                interval_minutes=1,
            )
            if intraday is not None and not intraday.empty:
                frames.append(intraday)
        except Exception as exc:
            return EMA10TrendSnapshot(
                False,
                None,
                None,
                None,
                f"INTRADAY_CANDLES_UNAVAILABLE:{type(exc).__name__}",
            )

        if not frames:
            return EMA10TrendSnapshot(
                False, None, None, None, "NO_UNDERLYING_CANDLES"
            )

        frame = pd.concat(frames, ignore_index=True)
        if "timestamp" not in frame.columns or "close" not in frame.columns:
            return EMA10TrendSnapshot(
                False, None, None, None, "UNDERLYING_CANDLE_COLUMNS_MISSING"
            )

        timestamps = pd.to_datetime(
            frame["timestamp"],
            errors="coerce",
            utc=True,
        )
        closes = pd.to_numeric(frame["close"], errors="coerce")
        source = pd.DataFrame(
            {"timestamp": timestamps, "close": closes}
        ).dropna()
        if source.empty:
            return EMA10TrendSnapshot(
                False, None, None, None, "NO_VALID_UNDERLYING_CANDLES"
            )

        source["timestamp"] = source["timestamp"].dt.tz_convert(
            "Asia/Kolkata"
        )
        source = (
            source.sort_values("timestamp")
            .drop_duplicates("timestamp", keep="last")
        )

        bars = (
            source.set_index("timestamp")
            .resample(
                "5min",
                origin="start_day",
                offset="15min",
                label="left",
                closed="left",
            )
            .agg(
                close=("close", "last"),
                source_rows=("close", "count"),
            )
            .dropna(subset=["close"])
        )
        bars = bars[bars["source_rows"] >= 5].copy()
        if bars.empty:
            return EMA10TrendSnapshot(
                False, None, None, None, "NO_COMPLETED_5M_CANDLES"
            )

        bars["ema10"] = bars["close"].ewm(
            span=10,
            adjust=False,
        ).mean()
        today_bars = bars[bars.index.date == today]
        if today_bars.empty:
            return EMA10TrendSnapshot(
                False, None, None, None, "NO_COMPLETED_5M_CANDLE_TODAY"
            )

        latest = today_bars.iloc[-1]
        timestamp = today_bars.index[-1]
        return EMA10TrendSnapshot(
            True,
            round(float(latest["close"]), 4),
            round(float(latest["ema10"]), 4),
            timestamp.isoformat(),
            "READY",
        )


RedBarTrendAutomationService = TrendAwarePaperAutomationService
