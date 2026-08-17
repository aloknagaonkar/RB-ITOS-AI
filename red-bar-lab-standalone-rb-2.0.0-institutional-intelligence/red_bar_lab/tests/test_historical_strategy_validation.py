from dataclasses import dataclass
from datetime import date, timedelta

import pytest

from red_bar_lab.services.historical_strategy_adapters import DRIHistoricalStrategyAdapter, RedBarHistoricalStrategyAdapter
from red_bar_lab.services.historical_strategy_validation import (
    DayValidationResult,
    HistoricalStrategyValidationEngine,
    NormalizedReplayRow,
    StrategyDefinition,
    StrategyRegistry,
    calculate_metrics,
    default_strategy_registry,
    select_validation_dates,
)


def test_default_registry_tracks_dri_and_red_bar_versions():
    registry = default_strategy_registry()
    identities = {item.identity for item in registry.definitions()}
    assert 'DRI@1.0.0' in identities
    assert 'RED_BAR@1.0.0' in identities
    assert registry.versions('DRI') == ('1.0.0',)


def test_registry_rejects_non_research_strategy():
    registry = StrategyRegistry()
    with pytest.raises(ValueError, match='RESEARCH_ONLY'):
        registry.register(StrategyDefinition('BAD', 'Bad', '1.0.0', 'BAD', 'bad', research_scope='LIVE'))


def test_window_selection_supports_10_20_and_custom():
    start = date(2026, 7, 1)
    dates = tuple(start + timedelta(days=i) for i in range(30))
    assert len(select_validation_dates(dates, window='10_DAY')) == 10
    assert len(select_validation_dates(dates, window='20_DAY')) == 20
    custom = select_validation_dates(dates, window='CUSTOM', custom_start=start + timedelta(days=5), custom_end=start + timedelta(days=9))
    assert len(custom) == 5


def _day(day, returns, ready=True):
    return DayValidationResult(
        trading_date=day,
        ready=ready,
        fidelity='HIGH' if ready else 'BLOCKED',
        readiness_reason='READY' if ready else 'NO_DATA',
        rows=tuple(NormalizedReplayRow(day, 'EXECUTE', 'EXECUTED', 'WIN' if value > 0 else 'LOSS', value, max(value, 0), min(value, 0)) for value in returns),
    )


def test_shared_metrics_include_drawdown_and_promotion():
    start = date(2026, 7, 1)
    metrics = calculate_metrics(tuple(_day(start + timedelta(days=i), [2.0]) for i in range(10)))
    assert metrics.ready_days == 10
    assert metrics.trade_count == 10
    assert metrics.win_rate_pct == 100.0
    assert metrics.maximum_drawdown_pct == 0.0
    assert metrics.promotion_eligible is True


def test_drawdown_is_calculated_from_cumulative_returns():
    start = date(2026, 7, 1)
    metrics = calculate_metrics(
        (_day(start, [10.0]), _day(start + timedelta(days=1), [-15.0]), _day(start + timedelta(days=2), [4.0])),
        minimum_ready_days=0,
        minimum_trades=0,
        minimum_win_rate_pct=0,
        maximum_allowed_drawdown_pct=100,
    )
    assert metrics.maximum_drawdown_pct == 15.0


@dataclass
class FakeRow:
    decision: str = 'EXECUTE'
    execution: str = 'EXECUTED'
    outcome_result: str = 'WIN'
    option_return_pct: float = 5.0
    data_fidelity: str = 'HIGH'

    def as_dict(self):
        return self.__dict__.copy()


@dataclass
class FakeReplayResult:
    rows: tuple = (FakeRow(),)
    replay_ready: bool = True
    data_fidelity: str = 'HIGH'
    replay_fidelity_reason: str = 'READY'
    option_contract_coverage_pct: float = 100.0
    option_candle_coverage_pct: float = 100.0
    option_oi_coverage_pct: float = 100.0


class FakeReplay:
    def run_day(self, instrument_key, trading_date):
        return FakeReplayResult()


@pytest.mark.parametrize('adapter_type', [DRIHistoricalStrategyAdapter, RedBarHistoricalStrategyAdapter])
def test_existing_replays_are_wrapped_as_generic_adapters(adapter_type):
    adapter = adapter_type(FakeReplay())
    result = adapter.run_day('NSE_INDEX|Nifty 50', date(2026, 8, 1))
    assert result.ready is True
    assert result.rows[0].return_pct == 5.0
    assert adapter.research_only is True


def test_engine_blocks_non_research_adapter():
    registry = StrategyRegistry()
    registry.register(StrategyDefinition('X', 'X', '1', 'X', 'x'))

    class Unsafe:
        adapter_id = 'X'
        research_only = False

    engine = HistoricalStrategyValidationEngine(registry, [Unsafe()])
    with pytest.raises(RuntimeError, match='not research-only'):
        engine.validate(strategy_id='X', version='1', instrument_key='NIFTY', trading_dates=[date(2026, 8, 1)])


def test_engine_supports_side_by_side_comparison():
    registry = default_strategy_registry()
    engine = HistoricalStrategyValidationEngine(
        registry,
        [DRIHistoricalStrategyAdapter(FakeReplay()), RedBarHistoricalStrategyAdapter(FakeReplay())],
    )
    reports = engine.compare(
        strategies=[('DRI', '1.0.0'), ('RED_BAR', '1.0.0')],
        instrument_key='NIFTY',
        trading_dates=[date(2026, 8, 1)],
    )
    assert [item.strategy.strategy_id for item in reports] == ['DRI', 'RED_BAR']
    assert all(item.research_scope == 'RESEARCH_ONLY' for item in reports)
