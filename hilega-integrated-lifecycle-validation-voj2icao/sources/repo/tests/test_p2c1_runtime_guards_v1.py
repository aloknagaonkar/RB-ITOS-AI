
from datetime import datetime
from zoneinfo import ZoneInfo

from market_lab.oi_vwap_runtime_guards_v1 import (
    classify_oi_feature_error,
    checkpoint_key_from_received_at,
    classify_p2_checkpoint,
)

IST = ZoneInfo("Asia/Kolkata")


def test_baseline_error_is_specific():
    err = ValueError("09:20 session baseline unavailable")
    assert classify_oi_feature_error(err) == "SESSION_BASELINE_UNAVAILABLE"


def test_unknown_feature_error_stays_generic():
    assert classify_oi_feature_error(ValueError("x")) == "OI_FEATURE_FAILED"


def test_checkpoint_key_dedupes_15_second_samples():
    a = checkpoint_key_from_received_at("2026-09-16T10:20:02+05:30")
    b = checkpoint_key_from_received_at("2026-09-16T10:24:59+05:30")
    c = checkpoint_key_from_received_at("2026-09-16T10:25:00+05:30")
    assert a == b
    assert c != a


def test_p2_must_be_exact_next_5m_checkpoint():
    assert classify_p2_checkpoint(
        p1_time="2026-09-16T10:20:00+05:30",
        current_time="2026-09-16T10:25:03+05:30",
    ) == "EXPECTED_P2"

    assert classify_p2_checkpoint(
        p1_time="2026-09-16T10:20:00+05:30",
        current_time="2026-09-16T10:30:00+05:30",
    ) == "P2_CHECKPOINT_MISSED"
