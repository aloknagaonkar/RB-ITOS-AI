from scripts.validate_hilega_milega_opening_gap_diagnostic_v2_0 import gap_metrics


def test_gap_up_full_retention():
    m = gap_metrics(100.0, 110.0, 110.0, 110.0)
    assert m["gap_points"] == 10.0
    assert m["gap_retained_pct_0920"] == 100.0
    assert m["gap_fill_pct_0920"] == 0.0


def test_gap_up_partial_fill():
    m = gap_metrics(100.0, 110.0, 106.0, 104.0)
    assert m["gap_retained_pct_0920"] == 60.0
    assert m["gap_fill_pct_0920"] == 40.0
    assert m["gap_retained_pct_0925"] == 40.0
    assert m["gap_fill_pct_0925"] == 60.0


def test_gap_up_overextension_above_open():
    m = gap_metrics(100.0, 110.0, 112.0, 113.0)
    assert m["gap_retained_pct_0920"] == 120.0
    assert m["gap_fill_pct_0920"] == -20.0


def test_gap_down_math_is_symmetric():
    m = gap_metrics(100.0, 90.0, 94.0, 96.0)
    assert m["gap_points"] == -10.0
    assert m["gap_retained_pct_0920"] == 60.0
    assert m["gap_fill_pct_0920"] == 40.0
