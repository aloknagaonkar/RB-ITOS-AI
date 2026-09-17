from backend.market_lab.oi_fallback_semantic_overlap_diagnostic_v1 import (
    OIObservation,
    compare_exact_overlap,
    summarize_session,
)


def obs(ts, strike, side, oi):
    return OIObservation(ts, float(strike), side, float(oi))


def test_exact_overlap_and_difference():
    p = [obs("2026-01-01T10:00:00+05:30", 100, "CE", 1000)]
    o = [obs("2026-01-01T10:00:00+05:30", 100, "CE", 1000)]
    rows, counts = compare_exact_overlap("2026-01-01", p, o)
    assert counts["exact_overlap_observations"] == 1
    assert rows[0].exact_match is True
    assert rows[0].absolute_relative_difference == 0.0


def test_relative_difference_thresholds():
    p = [obs("2026-01-01T10:00:00+05:30", 100, "PE", 1000)]
    o = [obs("2026-01-01T10:00:00+05:30", 100, "PE", 1005)]
    rows, _ = compare_exact_overlap("2026-01-01", p, o)
    r = rows[0]
    assert r.exact_match is False
    assert r.within_0_5_pct is True
    assert r.within_1_pct is True
    assert abs(r.relative_difference_vs_positioning - 0.005) < 1e-12


def test_only_exact_timestamp_strike_side_matches():
    p = [
        obs("2026-01-01T10:00:00+05:30", 100, "CE", 1000),
        obs("2026-01-01T10:00:00+05:30", 100, "PE", 2000),
    ]
    o = [
        obs("2026-01-01T10:05:00+05:30", 100, "CE", 1000),
        obs("2026-01-01T10:00:00+05:30", 100, "PE", 2000),
    ]
    rows, counts = compare_exact_overlap("2026-01-01", p, o)
    assert len(rows) == 1
    assert rows[0].side == "PE"
    assert counts["positioning_only_observations"] == 1
    assert counts["option_ohlc_only_observations"] == 1


def test_zero_positioning_oi_has_no_relative_percentage():
    p = [obs("2026-01-01T10:00:00+05:30", 100, "CE", 0)]
    o = [obs("2026-01-01T10:00:00+05:30", 100, "CE", 10)]
    rows, counts = compare_exact_overlap("2026-01-01", p, o)
    summary = summarize_session("2026-01-01", rows, counts)
    assert rows[0].relative_difference_vs_positioning is None
    assert summary["zero_positioning_oi_overlap_count"] == 1


def test_duplicate_exact_keys_fail_closed():
    p = [
        obs("2026-01-01T10:00:00+05:30", 100, "CE", 1000),
        obs("2026-01-01T10:00:00+05:30", 100, "CE", 1001),
    ]
    o = [obs("2026-01-01T10:00:00+05:30", 100, "CE", 1000)]
    try:
        compare_exact_overlap("2026-01-01", p, o)
    except ValueError as exc:
        assert "Duplicate positioning exact key" in str(exc)
    else:
        raise AssertionError("Expected duplicate exact-key failure")
