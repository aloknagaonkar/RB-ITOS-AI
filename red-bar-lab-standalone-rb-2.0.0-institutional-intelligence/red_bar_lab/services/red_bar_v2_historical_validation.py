from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Sequence

from red_bar_lab.services.historical_strategy_runner import (
    build_historical_strategy_validation_engine,
)
from red_bar_lab.services.historical_strategy_validation import (
    DayValidationResult,
    NormalizedReplayRow,
    StrategyDefinition,
    StrategyRegistry,
    StrategyValidationReport,
    default_strategy_registry,
)
from red_bar_lab.services.red_bar_v2_evidence_collection import RedBarV2EvidenceStore
from red_bar_lab.services.red_bar_v2_historical_replay import replay_red_bar_v2_day


RED_BAR_V2_ADAPTER_ID = "RED_BAR_V2_REPLAY"
RED_BAR_V2_STRATEGY_ID = "RED_BAR_V2"
RED_BAR_V2_VERSION = "2.0.0"


def red_bar_v2_strategy_registry() -> StrategyRegistry:
    """Return the existing research registry with Red Bar V2 added."""
    registry = default_strategy_registry()
    registry.register(
        StrategyDefinition(
            strategy_id=RED_BAR_V2_STRATEGY_ID,
            display_name="Red Bar V2 — RSI/VWAP Reversal",
            version=RED_BAR_V2_VERSION,
            adapter_id=RED_BAR_V2_ADAPTER_ID,
            description=(
                "Validated NEXT_RED_CANDLE RSI/VWAP initial and reversal replay. "
                "Research-only; does not create paper or live orders."
            ),
        )
    )
    return registry


class RedBarV2HistoricalStrategyAdapter:
    adapter_id = RED_BAR_V2_ADAPTER_ID
    research_only = True

    def __init__(self, replay_reader, evidence_store: RedBarV2EvidenceStore | None = None):
        self.replay_reader = replay_reader
        self.evidence_store = evidence_store

    def run_day(self, instrument_key: str, trading_date: date) -> DayValidationResult:
        candles = self.replay_reader.read_day(
            instrument_key,
            trading_date,
            interval_minutes=1,
        )
        if candles is None or candles.empty:
            return DayValidationResult(
                trading_date=trading_date,
                ready=False,
                fidelity="BLOCKED",
                readiness_reason="NO_CACHED_ONE_MINUTE_CANDLES",
                coverage_basis="UNDERLYING_1M",
            )

        try:
            result = replay_red_bar_v2_day(
                candles,
                instrument_key=instrument_key,
            )
        except Exception as exc:
            if self.evidence_store is not None:
                self.evidence_store.record_replay_error(
                    instrument_key=instrument_key,
                    trading_date=trading_date.isoformat(),
                    error=f"{type(exc).__name__}:{exc}",
                )
            raise

        if self.evidence_store is not None:
            self.evidence_store.record_replay(result)

        rows: list[NormalizedReplayRow] = []
        for event in result.events:
            if event.event_type != "CANDIDATE_ADMISSION":
                continue
            decision = event.direction or "NO_DIRECTION"
            execution = (
                f"SHADOW_{event.option_side}"
                if event.candidate_allowed and event.option_side
                else "BLOCKED"
            )
            rows.append(
                NormalizedReplayRow(
                    trading_date=trading_date,
                    decision=decision,
                    execution=execution,
                    outcome_result=(
                        event.admission_code
                        or ("ADMITTED" if event.candidate_allowed else "BLOCKED")
                    ),
                    return_pct=None,
                    data_fidelity="UNDERLYING_ONLY",
                )
            )

        return DayValidationResult(
            trading_date=trading_date,
            ready=True,
            fidelity="UNDERLYING_ONLY",
            readiness_reason=(
                f"READY: admitted={result.admitted_candidates}; "
                f"blocked={result.blocked_candidates}; "
                f"final_state={result.final_trade_state}"
            ),
            rows=tuple(rows),
            coverage_basis="UNDERLYING_1M",
            candle_coverage_pct=100.0,
            global_replay_ready=True,
            strategy_relevant_status="READY",
            strategy_relevant_reason="Red Bar V2 requires underlying one-minute OHLCV only.",
        )


def _evidence_store_for_reader(replay_reader) -> RedBarV2EvidenceStore | None:
    layout = getattr(replay_reader, "layout", None)
    settings = getattr(layout, "settings", None)
    runs_root = getattr(settings, "runs_root", None)
    if runs_root is None:
        return None
    root = Path(runs_root) / "red_bar_v2" / "promotion_evidence"
    return RedBarV2EvidenceStore(root)


def run_red_bar_v2_historical_strategy_validation(
    *,
    replay_reader,
    option_chain_sync,
    instrument_key: str,
    trading_dates: Sequence[date],
    strategies: Sequence[tuple[str, str]],
    registry: StrategyRegistry | None = None,
) -> tuple[StrategyValidationReport, ...]:
    """Run the existing generic validator with the additive Red Bar V2 adapter."""
    if not trading_dates:
        raise ValueError("No cached trading dates were selected.")
    if not strategies:
        raise ValueError("Select at least one strategy for validation.")

    active_registry = registry or red_bar_v2_strategy_registry()
    engine = build_historical_strategy_validation_engine(
        replay_reader,
        option_chain_sync,
        registry=active_registry,
    )
    engine.adapters[RED_BAR_V2_ADAPTER_ID] = RedBarV2HistoricalStrategyAdapter(
        replay_reader,
        evidence_store=_evidence_store_for_reader(replay_reader),
    )
    return engine.compare(
        strategies=tuple(strategies),
        instrument_key=instrument_key,
        trading_dates=tuple(trading_dates),
    )
