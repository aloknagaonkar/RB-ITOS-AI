from scripts.validate_hilega_milega_opening_120_session_v2_1 import (
    gap_context,
    opening_status,
)


def test_no_opening_alignment():
    s = opening_status(
        60, 55, 58,   # not RSI > EMA > WMA
        61, 58,
        62, 59,
    )
    assert s == "NO_OPENING_ALIGNMENT"


def test_reject_at_0920():
    s = opening_status(
        70, 60, 55,
        54, 56,
        60, 57,
    )
    assert s == "OPENING_REJECTED_0920"


def test_reject_at_0925():
    s = opening_status(
        70, 60, 55,
        65, 56,
        54, 56,
    )
    assert s == "OPENING_REJECTED_0925"


def test_confirm_at_0925():
    s = opening_status(
        70, 60, 55,
        65, 56,
        62, 57,
    )
    assert s == "OPENING_BULLISH_CONFIRMED"


def test_gap_context_math():
    g = gap_context(100, 110, 106, 104)
    assert g["gap_points"] == 10
    assert g["gap_retained_pct_0920"] == 60
    assert g["gap_retained_pct_0925"] == 40
