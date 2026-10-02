from scripts.validate_hilega_milega_bullish_gap_audit_v1_4 import gap_metrics


def test_expanding_gap_passes_without_delay():
    m = gap_metrics(-2.93, 0.0, 2.17, 0.0)
    assert m["gap_expanding"] is True
    assert m["entry_delay_minutes"] == 0


def test_shrinking_gap_fails_without_waiting_next_candle():
    m = gap_metrics(2.0, 0.0, 1.0, 0.0)
    assert m["gap_expanding"] is False
    assert m["entry_delay_minutes"] == 0


def test_negative_to_positive_gap_is_strong_expansion():
    m = gap_metrics(55.2532, 55.8595, 60.1427, 56.3980)
    assert m["prev_gap"] < 0
    assert m["current_gap"] > 0
    assert m["gap_change"] > 0


def test_positive_gap_can_still_fail_if_compressing():
    m = gap_metrics(5.0, 3.0, 5.5, 4.0)
    assert m["current_gap"] > 0
    assert m["gap_change"] < 0
    assert m["gap_expanding"] is False
