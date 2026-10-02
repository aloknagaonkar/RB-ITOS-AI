from datetime import datetime, timedelta, timezone

from market_lab.midpoint_primary_continuation_option_backtest_v1 import (
    ROUND_TRIP_COST_PCT,
    _atm_row,
    _net,
    _ret,
    _target_stop_result,
)

IST = timezone(timedelta(hours=5, minutes=30))


def test_exact_atm_only_no_nearest_fallback():
    rows = [
        {"strike_offset": "-1", "strike": "24950"},
        {"strike_offset": "1", "strike": "25050"},
    ]
    assert _atm_row(rows) is None


def test_exact_atm_is_selected():
    rows = [
        {"strike_offset": "-1", "strike": "24950"},
        {"strike_offset": "0", "strike": "25000"},
        {"strike_offset": "1", "strike": "25050"},
    ]
    assert _atm_row(rows)["strike"] == "25000"


def test_net_return_subtracts_fixed_roundtrip_cost():
    assert ROUND_TRIP_COST_PCT == 0.50
    assert _net(5.0) == 4.5


def test_option_return():
    assert _ret(110.0, 100.0) == 10.0


def test_target_first():
    bars = [
        (0, {"high": "103", "low": "99"}),
        (1, {"high": "106", "low": "101"}),
    ]
    result = _target_stop_result(
        bars,
        entry=100.0,
        target_pct=5.0,
        stop_pct=10.0,
    )
    assert result["result"] == "TARGET_FIRST"
    assert result["minute"] == 1


def test_ambiguous_same_bar():
    bars = [(0, {"high": "106", "low": "89"})]
    result = _target_stop_result(
        bars,
        entry=100.0,
        target_pct=5.0,
        stop_pct=10.0,
    )
    assert result["result"] == "AMBIGUOUS_SAME_BAR"
