import csv
import json
from pathlib import Path

import pytest

from market_lab.midpoint_v3_2_oos_h_freeze_contract_v1 import (
    EXIT_POLICY_ID,
    FROZEN_EXIT,
    build_contract,
)
from market_lab.midpoint_v3_2_oos_h_frozen_exit_replay_v1 import (
    pct_return,
    simulate_frozen_exit,
)
from market_lab.midpoint_v3_2_oos_h_final_validation_v1 import final_decision


def candle(ts, o, h, l, c):
    return {
        "session_date": "2026-01-01",
        "instrument_key": "X",
        "timestamp": ts,
        "open": float(o),
        "high": float(h),
        "low": float(l),
        "close": float(c),
        "_dt": __import__("datetime").datetime.fromisoformat(ts),
    }


def trade(entry=100.0):
    return {
        "block": "OOS_H",
        "session_date": "2026-01-01",
        "direction": "BULLISH",
        "instrument_key": "X",
        "entry_timestamp": "2026-01-01T09:30:00+05:30",
        "entry_price": entry,
        "option_side": "CE",
        "strike": 25000,
    }


def flat_path():
    return [
        candle(
            f"2026-01-01T09:{30+i:02d}:00+05:30",
            100, 101, 99, 100
        )
        for i in range(15)
    ]


def test_initial_stop_touch_is_minus_5_gross_minus_cost_net():
    path = flat_path()
    path[0]["low"] = 94.0
    out = simulate_frozen_exit(trade=trade(), candles=path)
    assert out["exit_reason"] == "STOP_TOUCH"
    assert round(out["gross_return_pct"], 8) == -5.0
    assert round(out["net_return_pct"], 8) == -5.5


def test_gap_through_stop_uses_open():
    path = flat_path()
    # Entry bar remains reconciled to the 100 entry open.
    # The next bar gaps below the still-active 95 stop.
    path[1]["open"] = 94.0
    path[1]["high"] = 95.0
    path[1]["low"] = 93.0
    path[1]["close"] = 94.5
    out = simulate_frozen_exit(trade=trade(), candles=path)
    assert out["exit_reason"] == "STOP_GAP"
    assert out["exit_price"] == 94.0


def test_breakeven_activation_is_next_bar():
    path = flat_path()
    # Bar 1 reaches +6 but dips to 98. It must NOT stop at breakeven same bar.
    path[0]["high"] = 106.0
    path[0]["low"] = 98.0
    path[0]["close"] = 104.0
    # Next bar has BE active and touches 100.
    path[1]["open"] = 104.0
    path[1]["high"] = 105.0
    path[1]["low"] = 99.0
    path[1]["close"] = 100.0
    out = simulate_frozen_exit(trade=trade(), candles=path)
    assert out["exit_reason"] == "STOP_TOUCH"
    assert out["exit_price"] == 100.0
    assert round(out["net_return_pct"], 8) == -0.5


def test_trail_activation_is_next_bar():
    path = flat_path()
    # First bar reaches +12: next-bar trail = max(BE, 112*0.97)=108.64.
    path[0]["high"] = 112.0
    path[0]["low"] = 98.0
    path[0]["close"] = 110.0
    path[1]["open"] = 110.0
    path[1]["high"] = 111.0
    path[1]["low"] = 108.0
    path[1]["close"] = 109.0
    out = simulate_frozen_exit(trade=trade(), candles=path)
    assert out["exit_reason"] == "STOP_TOUCH"
    assert round(out["exit_price"], 8) == 108.64


def test_time_exit_after_15_bars():
    path = flat_path()
    path[-1]["close"] = 103.0
    out = simulate_frozen_exit(trade=trade(), candles=path)
    assert out["exit_reason"] == "TIME_EXIT"
    assert out["exit_price"] == 103.0
    assert round(out["net_return_pct"], 8) == 2.5


def test_final_decision_hold_for_small_sample():
    decision, _ = final_decision(
        trade_count=9,
        mean_net_pct=10.0,
        profit_factor=5.0,
        integrity_ok=True,
        minimum_trades=10,
    )
    assert decision == "HOLD_INSUFFICIENT_SAMPLE"


def test_final_decision_pass_requires_positive_mean_and_pf():
    decision, _ = final_decision(
        trade_count=10,
        mean_net_pct=1.0,
        profit_factor=1.2,
        integrity_ok=True,
        minimum_trades=10,
    )
    assert decision == "PASS_CANDIDATE_FOR_PAPER_TRADING_REVIEW"


def test_final_decision_fails_negative_economics():
    decision, _ = final_decision(
        trade_count=20,
        mean_net_pct=-0.1,
        profit_factor=1.2,
        integrity_ok=True,
        minimum_trades=10,
    )
    assert decision == "FAIL_ECONOMICS"


def test_integrity_failure_overrides_good_economics():
    decision, _ = final_decision(
        trade_count=20,
        mean_net_pct=2.0,
        profit_factor=2.0,
        integrity_ok=False,
        minimum_trades=10,
    )
    assert decision == "FAIL_INTEGRITY"


def test_freeze_contract_requires_robustness_supportive(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("x=1\n")
    payload = {
        "research_version": "MIDPOINT_V3_2_TEMPORAL_DEPENDENCE_ROBUSTNESS_V1",
        "frozen_policy_id": EXIT_POLICY_ID,
        "research_assessment": {"label": "PROMISING_BUT_UNCERTAIN"},
        "leakage_guard": {
            "oos_h_used": False,
            "entry_state_machine_modified": False,
            "exit_policy_modified": False,
        },
    }
    with pytest.raises(ValueError, match="ROBUSTNESS_SUPPORTIVE"):
        build_contract(robustness_payload=payload, files=[f])


def test_frozen_exit_constants():
    assert FROZEN_EXIT == {
        "initial_stop_pct": 5.0,
        "breakeven_trigger_pct": 5.0,
        "trail_activation_pct": 10.0,
        "trail_distance_pct": 3.0,
        "max_hold_minutes": 15,
        "breakeven_and_trailing_activate_next_bar": True,
        "gap_through_stop_exits_at_open": True,
    }
