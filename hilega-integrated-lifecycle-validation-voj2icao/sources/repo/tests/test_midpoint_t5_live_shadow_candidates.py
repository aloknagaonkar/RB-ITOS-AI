from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_lab.midpoint_strategy.config import MidpointShadowConfig
from market_lab.midpoint_strategy.entry_health_live_v1 import (
    MidpointEntryHealthLiveV1,
    entry_health_label,
    evaluate_t5_candidates,
)
from market_lab.midpoint_strategy.workspace_contract import midpoint_workspace_status


def test_two_of_three_and_combined_edge_are_independent_candidates():
    snapshot = {
        "available": True,
        "di_failure": False,
        "combined_edge_failure": True,
        "price_momentum_failure": True,
    }
    result = evaluate_t5_candidates(snapshot)
    assert result["failure_count"] == 2
    assert result["two_of_three"] is True
    assert result["combined_edge"] is True


def test_incomplete_warmup_never_triggers_candidate():
    result = evaluate_t5_candidates({"available": False})
    assert result == {
        "available": False,
        "two_of_three": False,
        "combined_edge": False,
    }


def test_entry_health_label_uses_same_natural_two_of_three_evidence():
    assert entry_health_label({
        "available": True,
        "di_failure": False,
        "combined_edge_failure": False,
        "price_momentum_failure": True,
    }) == {"health": "HEALTHY", "support_count": 2}
    assert entry_health_label({
        "available": True,
        "di_failure": True,
        "combined_edge_failure": True,
        "price_momentum_failure": False,
    }) == {"health": "UNHEALTHY", "support_count": 1}


def test_live_health_uses_only_sequential_completed_bars():
    engine = MidpointEntryHealthLiveV1()
    start = datetime(2026, 10, 1, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata"))
    raw = None
    for minute in range(35):
        close = 23000.0 - minute
        raw = engine.update(
            timestamp=start + timedelta(minutes=minute),
            open_=close + 0.5,
            high=close + 1.0,
            low=close - 1.0,
            close=close,
            futures_open=close + 20.5,
            futures_close=close + 20.0,
            futures_vwap=23010.0,
            futures_volume=1000.0 + minute,
        )
    snapshot = engine.directional_snapshot(raw, "BEARISH")
    assert snapshot["available"] is True
    assert snapshot["directional_di_spread"] > 0
    assert snapshot["price_momentum_support"] == 1.0


def test_workspace_exposes_both_observation_candidates():
    workspace = midpoint_workspace_status(MidpointShadowConfig())
    assert workspace["management"]["t5_two_of_three_candidate_enabled"] is True
    assert workspace["management"]["t5_combined_edge_candidate_enabled"] is True
    assert workspace["safety"] == {
        "observation_only": True,
        "execution_enabled": False,
        "paper_order_enabled": False,
        "quantity": None,
    }
