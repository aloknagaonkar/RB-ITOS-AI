
from market_lab.oi_vwap_causal_runtime_v1 import (
    _classify_oi_feature_error,
    _classify_p2_checkpoint,
)


def test_baseline_error_specific():
    assert _classify_oi_feature_error(
        ValueError("09:20 session baseline unavailable")
    ) == "SESSION_BASELINE_UNAVAILABLE"


def test_other_feature_error_generic():
    assert _classify_oi_feature_error(ValueError("x")) == "OI_FEATURE_FAILED"


def test_p2_exact_next_checkpoint():
    assert _classify_p2_checkpoint(
        "2026-09-16T10:20:00+05:30",
        "2026-09-16T10:25:02+05:30",
    ) == "EXPECTED_P2"


def test_p2_gap_is_rejected():
    assert _classify_p2_checkpoint(
        "2026-09-16T10:20:00+05:30",
        "2026-09-16T10:30:00+05:30",
    ) == "P2_CHECKPOINT_MISSED"
