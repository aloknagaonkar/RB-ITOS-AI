from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from time import monotonic
from typing import Any, Iterable

import pandas as pd

from red_bar_lab.execution.automation import RedBarPaperAutomationService
from red_bar_lab.execution.opportunity_engine import OpportunityIntelligenceEngine
from red_bar_lab.execution.paper_engine import RedBarPaperExecutionEngine
from red_bar_lab.execution.performance_selection import (
    PerformanceTradeSelectionEngine,
    TradeSelectionEvaluation,
    _num as _selection_num,
)


@dataclass(frozen=True)
class EMA10TrendSnapshot:
    ready: bool
    close: float | None
    ema10: float | None
    timestamp: str | None
    reason: str


class EMA10OpportunityIntelligenceEngine(OpportunityIntelligenceEngine):
    """Opportunity engine where NIFTY 5m EMA10 owns continuation validity.

    Reward Remaining / Move Consumed are still calculated and persisted by the
    parent engine for historical comparison, but REWARD_CONSUMED is disabled as
    an execution blocker. A completed underlying 5-minute close across EMA10 is
    the replacement continuation invalidation rule.
    """

    def __init__(self, **kwargs):
        kwargs["minimum_reward_remaining_pct"] = -1.0
        super().__init__(**kwargs)

    def evaluate(self, **kwargs):
        result = super().evaluate(**kwargs)
        signal = kwargs.get("signal") or {}
        direction = str(signal.get("direction") or "").upper()
        ready = bool(signal.get("_ema10_5m_ready"))
        close = signal.get("_ema10_5m_close")
        ema10 = signal.get("_ema10_5m_value")

        blockers: list[str] = []
        if result.reason and result.reason != "OPPORTUNITY_HEALTH_PASS":
            blockers.extend(
                item.strip()
                for item in str(result.reason).split("|")
                if item.strip() and item.strip() != "REWARD_CONSUMED"
            )

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

        eligible = not blockers
        reason = (
            "OPPORTUNITY_HEALTH_PASS | EMA10_TREND_VALID"
            if eligible
            else " | ".join(dict.fromkeys(blockers))
        )
        return replace(
            result,
            eligible=eligible,
            decision=(f"BUY {kwargs['candidate'].contract.option_type}" if eligible else "SKIP"),
            reason=reason,
        )


class NoRewardRiskPerformanceTradeSelectionEngine(PerformanceTradeSelectionEngine):
    """Selection model with Reward/Risk retained as information only.

    The former 10% Reward/Risk weight is redistributed proportionally across the
    remaining four components so the published Selection Score remains 0-100:
      Candidate 38.89%, Opportunity 22.22%, Historical 27.78%, Execution 11.11%.
    """

    CANDIDATE_WEIGHT = 35.0 / 90.0
    OPPORTUNITY_WEIGHT = 20.0 / 90.0
    HISTORICAL_WEIGHT = 25.0 / 90.0
    EXECUTION_WEIGHT = 10.0 / 90.0

    def evaluate(
        self,
        *,
        candidate,
        candidate_rank: int,
        opportunity,
        historical_orders: Iterable[dict[str, object]],
        entry_mode: str,
        minimum_candidate_score: float,
        stop_loss_pct: float,
        target_pct: float,
        require_opportunity_gate: bool,
    ) -> TradeSelectionEvaluation:
        history = self.historical_performance(
            historical_orders,
            option_type=candidate.contract.option_type,
            entry_mode=entry_mode,
        )
        historical_score = self._historical_score(history)

        # Legacy configured R:R is preserved for storage/UI compatibility only.
        rr = (
            float(target_pct) / float(stop_loss_pct)
            if float(stop_loss_pct) > 0 else 0.0
        )
        execution_quality = min(
            100.0,
            (
                min(1.0, _selection_num(candidate.spread_score) / 15.0) * 45.0
                + min(1.0, _selection_num(candidate.liquidity_score) / 20.0) * 55.0
            ),
        )
        opportunity_score = _selection_num(opportunity.opportunity_score, 50.0)
        reward_remaining = _selection_num(opportunity.reward_remaining_pct, 100.0)

        selection_score = round(
            min(100.0, _selection_num(candidate.total_score)) * self.CANDIDATE_WEIGHT
            + min(100.0, opportunity_score) * self.OPPORTUNITY_WEIGHT
            + historical_score * self.HISTORICAL_WEIGHT
            + execution_quality * self.EXECUTION_WEIGHT,
            2,
        )

        hard_blockers: list[str] = []
        soft_evidence: list[str] = []
        if _selection_num(candidate.spread_score) <= 0:
            hard_blockers.append("SPREAD")
        if _selection_num(candidate.liquidity_score) <= 0:
            hard_blockers.append("LIQUIDITY")

        if _selection_num(candidate.total_score) < float(minimum_candidate_score):
            soft_evidence.append(
                f"CANDIDATE_SCORE={_selection_num(candidate.total_score):.2f}<MIN={float(minimum_candidate_score):.2f}"
            )
        if require_opportunity_gate and not bool(opportunity.eligible):
            soft_evidence.append(
                f"OPPORTUNITY_EXTENSION={str(getattr(opportunity, 'reason', 'NOT_ELIGIBLE'))}"
            )
        if selection_score < self.minimum_selection_score:
            soft_evidence.append(
                f"TSS={selection_score:.2f}<REFERENCE={self.minimum_selection_score:.2f}"
            )

        if history.evidence_ready:
            if _selection_num(history.win_rate_pct) < self.minimum_historical_win_rate_pct:
                soft_evidence.append(
                    f"HISTORICAL_WIN_RATE={_selection_num(history.win_rate_pct):.2f}<REFERENCE={self.minimum_historical_win_rate_pct:.2f}"
                )
            if history.profit_factor is None or _selection_num(history.profit_factor) < self.minimum_profit_factor:
                soft_evidence.append(
                    f"PROFIT_FACTOR={_selection_num(history.profit_factor):.3f}<REFERENCE={self.minimum_profit_factor:.3f}"
                )
            if history.expectancy_pct is None or _selection_num(history.expectancy_pct) <= self.minimum_expectancy_pct:
                soft_evidence.append(
                    f"EXPECTANCY={_selection_num(history.expectancy_pct):.3f}<=REFERENCE={self.minimum_expectancy_pct:.3f}"
                )

        eligible = not hard_blockers
        parts: list[str] = []
        if hard_blockers:
            parts.append("HARD_BLOCK:" + ",".join(hard_blockers))
        else:
            parts.append("NO_HARD_PERFORMANCE_BLOCKERS")
        if soft_evidence:
            parts.append("SOFT_EVIDENCE:" + "; ".join(soft_evidence))
        else:
            parts.append("SOFT_EVIDENCE:ALL_REFERENCE_LEVELS_MET")
        parts.append("REWARD_RISK_INFORMATIONAL_ONLY")

        return TradeSelectionEvaluation(
            candidate_rank=int(candidate_rank),
            candidate_symbol=candidate.contract.tradingsymbol,
            candidate_score=round(_selection_num(candidate.total_score), 2),
            opportunity_score=round(opportunity_score, 2),
            reward_remaining_pct=round(reward_remaining, 2),
            reward_risk_ratio=round(rr, 3),
            execution_quality_score=round(execution_quality, 2),
            historical_score=historical_score,
            selection_score=selection_score,
            historical=history,
            eligible=eligible,
            decision=(f"BUY {candidate.contract.option_type}" if eligible else "SKIP"),
            reason=" | ".join(parts),
        )


class NoTargetPaperExecutionEngine(RedBarPaperExecutionEngine):
    """Paper engine that keeps the hard stop but disables fixed profit targets."""

    def open_long_option(self, **kwargs):
        kwargs["target1_price"] = None
        kwargs["target2_price"] = None
        return super().open_long_option(**kwargs)


class TrendAwareDatabaseProxy:
    """Read-through DB proxy for EMA context and active-contract duplicate checks."""

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
        snapshot = self._trend_provider()
        enriched = dict(row)
        enriched["_ema10_5m_ready"] = snapshot.ready
        enriched["_ema10_5m_close"] = snapshot.close
        enriched["_ema10_5m_value"] = snapshot.ema10
        enriched["_ema10_5m_timestamp"] = snapshot.timestamp
        enriched["_ema10_5m_reason"] = snapshot.reason
        return enriched

    def read_signal_attempts(self, *args, **kwargs):
        rows = self._database.read_signal_attempts(*args, **kwargs)
        return [self._enrich(row) for row in rows]

    def read_signal_attempt_by_id(self, *args, **kwargs):
        return self._enrich(self._database.read_signal_attempt_by_id(*args, **kwargs))

    def paper_execution_exists_for_candidate(
        self,
        *,
        signal_id: str,
        account_id: str,
        instrument_token: int,
    ) -> bool:
        """Block the same contract only while OPEN or pending/active in queue.

        A CLOSED position is intentionally not a duplicate. It may be considered
        again by the full pipeline if the underlying EMA10 opportunity still holds.
        The check is account+instrument scoped, not signal scoped, so a second
        signal cannot stack the exact same open contract.
        """
        token = int(instrument_token)
        open_rows = self._database.read_open_paper_execution_orders(account_id)
        if any(int(row.get("instrument_token") or 0) == token for row in open_rows):
            return True

        try:
            queue_rows = self._database.read_execution_queue(limit=5000)
        except TypeError:
            queue_rows = self._database.read_execution_queue()
        for row in queue_rows or []:
            if int(row.get("instrument_token") or 0) != token:
                continue
            status = str(row.get("status") or "").upper()
            if status in self.ACTIVE_QUEUE_STATUSES:
                return True
        return False


class TrendAwarePaperAutomationService(RedBarPaperAutomationService):
    """RB execution service implementing agreed Changes 1-5.

    Change 1: EMA10 continuation replaces Reward Remaining / Move Consumed gate.
    Change 2: Reward/Risk has zero Selection Score weight.
    Change 3: Expected Value/Expectancy/Expected Win/Loss stay informational.
    Change 4: same contract blocked only while OPEN/PENDING; CLOSED can re-enter.
    Change 5: no fixed target; exit is driven by completed NIFTY 5m EMA10 loss.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._trend_cache_at = 0.0
        self._trend_cache = EMA10TrendSnapshot(
            False, None, None, None, "NOT_LOADED"
        )
        self._raw_database = self.database
        proxy = TrendAwareDatabaseProxy(self._raw_database, self._ema10_snapshot)
        self.database = proxy

        old_opportunity = self.opportunity_engine
        self.opportunity_engine = EMA10OpportunityIntelligenceEngine(
            minimum_opportunity_score=old_opportunity.minimum_opportunity_score,
            minimum_extended_candidate_score=old_opportunity.minimum_extended_candidate_score,
            minimum_liquidity_score=old_opportunity.minimum_liquidity_score,
            minimum_spread_score=old_opportunity.minimum_spread_score,
            minimum_momentum_score=old_opportunity.minimum_momentum_score,
        )

        old_selection = self.selection_engine
        self.selection_engine = NoRewardRiskPerformanceTradeSelectionEngine(
            minimum_selection_score=old_selection.minimum_selection_score,
            minimum_history_samples=old_selection.minimum_history_samples,
            minimum_historical_win_rate_pct=old_selection.minimum_historical_win_rate_pct,
            minimum_profit_factor=old_selection.minimum_profit_factor,
            minimum_expectancy_pct=old_selection.minimum_expectancy_pct,
        )

        # Change 3: payoff/expectancy metrics remain calculated/persisted, but the
        # expected-value threshold is disabled as execution authority.
        self.execution_committee.minimum_expected_value_pct = -1_000_000.0

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
        snapshot = self._load_ema10_snapshot()
        self._trend_cache = snapshot
        self._trend_cache_at = now_mono
        return snapshot

    def _load_ema10_snapshot(self) -> EMA10TrendSnapshot:
        adapter = self.zerodha
        provider = getattr(adapter, "provider", None)
        underlying_key = getattr(adapter, "underlying_key", None)
        if provider is None or not underlying_key:
            return EMA10TrendSnapshot(
                False, None, None, None, "UNDERLYING_CANDLE_PROVIDER_UNAVAILABLE"
            )

        today = date.today()
        frames: list[pd.DataFrame] = []
        try:
            historical = provider.historical_candles(
                underlying_key,
                today - timedelta(days=7),
                today - timedelta(days=1),
                interval_minutes=1,
            )
            if historical is not None and not historical.empty:
                frames.append(historical)
        except Exception:
            # Prior history improves EMA warm-up but today's completed candles are
            # still usable if the provider cannot serve the lookback temporarily.
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
                False, None, None, None, f"INTRADAY_CANDLES_UNAVAILABLE:{type(exc).__name__}"
            )

        if not frames:
            return EMA10TrendSnapshot(False, None, None, None, "NO_UNDERLYING_CANDLES")

        frame = pd.concat(frames, ignore_index=True)
        if "timestamp" not in frame.columns or "close" not in frame.columns:
            return EMA10TrendSnapshot(False, None, None, None, "UNDERLYING_CANDLE_COLUMNS_MISSING")

        ts = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True)
        close = pd.to_numeric(frame["close"], errors="coerce")
        source = pd.DataFrame({"timestamp": ts, "close": close}).dropna()
        if source.empty:
            return EMA10TrendSnapshot(False, None, None, None, "NO_VALID_UNDERLYING_CANDLES")
        source["timestamp"] = source["timestamp"].dt.tz_convert("Asia/Kolkata")
        source = source.sort_values("timestamp").drop_duplicates("timestamp", keep="last")

        bars = (
            source.set_index("timestamp")
            .resample(
                "5min",
                origin="start_day",
                offset="15min",
                label="left",
                closed="left",
            )
            .agg(close=("close", "last"), source_rows=("close", "count"))
            .dropna(subset=["close"])
        )
        bars = bars[bars["source_rows"] >= 5].copy()
        if bars.empty:
            return EMA10TrendSnapshot(False, None, None, None, "NO_COMPLETED_5M_CANDLES")

        bars["ema10"] = bars["close"].ewm(span=10, adjust=False).mean()
        current_day = bars[bars.index.date == today]
        if current_day.empty:
            return EMA10TrendSnapshot(False, None, None, None, "NO_COMPLETED_5M_CANDLE_TODAY")

        latest = current_day.iloc[-1]
        timestamp = current_day.index[-1]
        return EMA10TrendSnapshot(
            True,
            round(float(latest["close"]), 4),
            round(float(latest["ema10"]), 4),
            timestamp.isoformat(),
            "READY",
        )


# Friendly alias used by the production paper monitor.
RedBarTrendAutomationService = TrendAwarePaperAutomationService
