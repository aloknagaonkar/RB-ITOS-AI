from __future__ import annotations

from datetime import date
from typing import Sequence

from red_bar_lab.services.historical_decision_replay import (
    HistoricalDecisionReplayService,
)
from red_bar_lab.services.historical_dri_decision_replay import (
    HistoricalDRIDecisionReplayService,
)
from red_bar_lab.services.historical_strategy_adapters import (
    DRIHistoricalStrategyAdapter,
    RedBarHistoricalStrategyAdapter,
)
from red_bar_lab.services.historical_strategy_validation import (
    HistoricalStrategyValidationEngine,
    StrategyRegistry,
    StrategyValidationReport,
    default_strategy_registry,
)


def build_historical_strategy_validation_engine(
    replay_reader,
    option_chain_sync,
    *,
    registry: StrategyRegistry | None = None,
) -> HistoricalStrategyValidationEngine:
    """Build the research-only validator from existing replay services."""
    red_bar_replay = HistoricalDecisionReplayService(
        replay_reader,
        freshness_seconds=180,
        hard_expiry_seconds=900,
        minimum_confidence_pct=70.0,
        stop_loss_pct=15.0,
        target_pct=25.0,
        option_chain_sync=option_chain_sync,
    )
    dri_policy_replay = HistoricalDecisionReplayService(
        replay_reader,
        freshness_seconds=180,
        hard_expiry_seconds=900,
        minimum_confidence_pct=70.0,
        stop_loss_pct=15.0,
        target_pct=25.0,
        option_chain_sync=option_chain_sync,
    )
    dri_replay = HistoricalDRIDecisionReplayService(dri_policy_replay)
    return HistoricalStrategyValidationEngine(
        registry or default_strategy_registry(),
        (
            DRIHistoricalStrategyAdapter(dri_replay),
            RedBarHistoricalStrategyAdapter(red_bar_replay),
        ),
    )


def run_historical_strategy_validation(
    *,
    replay_reader,
    option_chain_sync,
    instrument_key: str,
    trading_dates: Sequence[date],
    strategies: Sequence[tuple[str, str]],
    registry: StrategyRegistry | None = None,
) -> tuple[StrategyValidationReport, ...]:
    """Run historical strategies without paper/live execution writes."""
    if not trading_dates:
        raise ValueError('No cached trading dates were selected.')
    if not strategies:
        raise ValueError('Select at least one strategy for validation.')

    engine = build_historical_strategy_validation_engine(
        replay_reader,
        option_chain_sync,
        registry=registry,
    )
    return engine.compare(
        strategies=tuple(strategies),
        instrument_key=instrument_key,
        trading_dates=tuple(trading_dates),
    )
