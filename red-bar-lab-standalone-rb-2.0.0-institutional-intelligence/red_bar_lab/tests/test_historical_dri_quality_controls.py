from dataclasses import dataclass
from red_bar_lab.services.historical_dri_quality import (
    DRIQualityConfig,
    SameDirectionReentryGate,
    calibration_eligible,
    filter_tradable_candidates,
)


@dataclass
class Contract:
    strike: float
    option_type: str = "CE"
    tradingsymbol: str = "TEST"


@dataclass
class Candidate:
    contract: Contract
    ltp: float
    total_score: float = 90.0


def test_rejects_extreme_otm_and_penny_option():
    result = filter_tradable_candidates(
        [
            Candidate(Contract(24300), 120.0),
            Candidate(Contract(26400), 0.8),
        ],
        spot=24287.0,
    )
    assert len(result.accepted) == 1
    assert result.rejected_count == 1
    assert "EXTREME_OTM" in result.reasons
    assert "PREMIUM_BELOW_MINIMUM" in result.reasons


def test_same_direction_reentry_cooldown():
    gate = SameDirectionReentryGate(cooldown_minutes=20)
    gate.record_taken("BEARISH", "2026-08-12T10:00:00+05:30")
    assert gate.reason("BEARISH", "2026-08-12T10:10:00+05:30")
    assert gate.reason("BEARISH", "2026-08-12T10:25:00+05:30") is None
    assert gate.reason("BULLISH", "2026-08-12T10:10:00+05:30") is None


def test_gap_rows_are_not_calibration_eligible():
    class Row:
        outcome_result = "UNKNOWN"
        blocker = "NO_RANK1_OPTION_AT_TIMESTAMP"
        learning_attribution = "OPTION_DATA_GAP"
    assert calibration_eligible(Row()) is False
