from market_lab.midpoint_v2_structural_reconstruction_v1 import (
    boundary_and_midpoint,
    first_existing,
)
from market_lab.midpoint_v2_research_foundation_v1 import assert_development_only
import pytest


def test_boundary_for_bullish_uses_reference_high():
    event = {
        "reference_high": 26000,
        "reference_low": 25940,
        "reference_midpoint": 25970,
    }
    boundary, midpoint = boundary_and_midpoint(event, "BULLISH")
    assert boundary == 26000
    assert midpoint == 25970


def test_boundary_for_bearish_uses_reference_low():
    event = {
        "reference_high": 26060,
        "reference_low": 26000,
        "reference_midpoint": 26030,
    }
    boundary, midpoint = boundary_and_midpoint(event, "BEARISH")
    assert boundary == 26000
    assert midpoint == 26030


def test_underlying_header_detection_supports_timestamp_close():
    headers = ["timestamp", "open", "high", "low", "close"]
    assert first_existing(headers, ("timestamp", "datetime")) == "timestamp"
    assert first_existing(headers, ("close", "close_price")) == "close"


def test_oos_h_remains_forbidden():
    with pytest.raises(ValueError, match="OOS_H"):
        assert_development_only(["TRAIN", "OOS_H"])
