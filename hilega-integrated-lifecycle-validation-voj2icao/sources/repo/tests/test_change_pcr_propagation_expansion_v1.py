from market_lab.change_pcr_propagation_expansion_v1 import (
    BASE_7,
    EXPANSION_12,
    EXPANSION_12_BULLISH,
    EXPANSION_12_BEARISH,
    summarize,
)


def test_frozen_cohorts():
    assert len(BASE_7) == 7
    assert len(EXPANSION_12) == 12
    assert len(EXPANSION_12_BULLISH) == 6
    assert len(EXPANSION_12_BEARISH) == 6
    assert BASE_7.isdisjoint(EXPANSION_12)


def test_summary():
    rows = [
        {
            "transition_within_5m": True,
            "transition_within_10m": True,
            "transition_within_15m": True,
            "persistent_3plus_hit_15m": True,
            "false_warning_15m": False,
        },
        {
            "transition_within_5m": False,
            "transition_within_10m": False,
            "transition_within_15m": False,
            "persistent_3plus_hit_15m": False,
            "false_warning_15m": True,
        },
    ]
    s = summarize(rows)
    assert s["candidates"] == 2
    assert s["precision_15m"] == 0.5
    assert s["persistent_3plus_precision_15m"] == 0.5
    assert s["false_warning_rate_15m"] == 0.5
