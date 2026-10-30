
import pytest
from pathlib import Path

from market_lab.oi_price_regime_transition_audit_v1_1 import (
    calculate_pcr,
    classify_futures_oi,
)

def test_futures_oi_status():
    assert classify_futures_oi(1, 1) == ("LONG_BUILDUP", "BULLISH")
    assert classify_futures_oi(-1, 1) == ("SHORT_BUILDUP", "BEARISH")
    assert classify_futures_oi(1, -1) == ("SHORT_COVERING", "BULLISH")
    assert classify_futures_oi(-1, -1) == ("LONG_UNWINDING", "BEARISH")


def test_calculate_pcr_uses_pe_over_ce():
    assert calculate_pcr(120.0, 100.0) == pytest.approx(1.2)
    assert calculate_pcr(80.0, 100.0) == pytest.approx(0.8)


def test_calculate_pcr_requires_nonzero_ce_and_both_sides():
    assert calculate_pcr(100.0, 0.0) is None
    assert calculate_pcr(100.0, None) is None
    assert calculate_pcr(None, 100.0) is None


def test_reference_oi_field_names_documented_for_horizons():
    expected = {
        "ce_oi_previous_same_strikes_5m",
        "pe_oi_previous_same_strikes_5m",
        "ce_oi_previous_same_strikes_10m",
        "pe_oi_previous_same_strikes_10m",
        "ce_oi_previous_same_strikes_15m",
        "pe_oi_previous_same_strikes_15m",
        "fixed_ce_oi_baseline_0920",
        "fixed_pe_oi_baseline_0920",
    }
    source = Path("backend/market_lab/oi_price_regime_transition_audit_v1_1.py").read_text()
    assert all(name in source for name in expected)
