from datetime import date

import pytest

from red_bar_lab.services.historical_strategy_runner import (
    build_historical_strategy_validation_engine,
    run_historical_strategy_validation,
)


class FakeOptionSync:
    pass


class FakeReader:
    pass


def test_runner_rejects_empty_date_selection():
    with pytest.raises(ValueError, match="No cached trading dates"):
        run_historical_strategy_validation(
            replay_reader=FakeReader(),
            option_chain_sync=FakeOptionSync(),
            instrument_key="NIFTY",
            trading_dates=(),
            strategies=(("RED_BAR", "1.0.0"),),
        )


def test_runner_rejects_empty_strategy_selection():
    with pytest.raises(ValueError, match="Select at least one strategy"):
        run_historical_strategy_validation(
            replay_reader=FakeReader(),
            option_chain_sync=FakeOptionSync(),
            instrument_key="NIFTY",
            trading_dates=(date(2026, 8, 1),),
            strategies=(),
        )


def test_builder_registers_both_research_only_adapters():
    engine = build_historical_strategy_validation_engine(
        FakeReader(),
        FakeOptionSync(),
    )
    assert set(engine.adapters) == {
        "DRI_REPLAY",
        "RED_BAR_REPLAY",
    }
    assert all(
        adapter.research_only
        for adapter in engine.adapters.values()
    )
