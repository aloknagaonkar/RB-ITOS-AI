from market_lab.midpoint_v3_2_temporal_stability_and_uncertainty_v1 import (
    bootstrap_mean_ci,
    permutation_mean_gap,
    rolling_windows,
    composition_decomposition,
)

def row(ts, ret, block="TRAIN", oi="STRONG", outcome="BREAK_AND_GO"):
    return {
        "entry_timestamp": ts,
        "session_date": ts[:10],
        "net_return_pct": ret,
        "block": block,
        "oi_quality": oi,
        "outcome_family": outcome,
    }

def test_bootstrap_is_deterministic():
    a = bootstrap_mean_ci([1.0, -1.0, 2.0], samples=1000, seed=7)
    b = bootstrap_mean_ci([1.0, -1.0, 2.0], samples=1000, seed=7)
    assert a == b

def test_permutation_gap_sign():
    out = permutation_mean_gap([-2, -1], [1, 2], samples=500, seed=9)
    assert out["observed_oos_minus_train_mean_pct_points"] == 3.0
    assert 0 <= out["two_sided_permutation_p"] <= 1

def test_rolling_windows_exact_count():
    rows = [row(f"2026-01-{i:02d}T10:00:00+05:30", float(i)) for i in range(1, 6)]
    out = rolling_windows(rows, window=3)
    assert len(out) == 3
    assert out[0]["trade_count"] == 3

def test_composition_decomposition_same_mix_zero_composition():
    train = [
        row("2026-01-01T10:00:00+05:30", -1, oi="STRONG"),
        row("2026-01-02T10:00:00+05:30", -1, oi="SECONDARY"),
    ]
    oos = [
        row("2026-02-01T10:00:00+05:30", 1, block="OOS_A", oi="STRONG"),
        row("2026-02-02T10:00:00+05:30", 1, block="OOS_A", oi="SECONDARY"),
    ]
    out = composition_decomposition(train, oos, "oi_quality")
    assert abs(out["composition_component_pct_points_common_categories"]) < 1e-12
    assert abs(out["within_segment_component_pct_points_common_categories"] - 2.0) < 1e-12
