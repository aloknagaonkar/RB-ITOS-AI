from red_bar_lab.services.readiness_freshness_alignment import (
    assess_collector_freshness,
    assess_signal_alignment,
    summarize_alignment_coverage,
)


def test_collector_freshness_is_independent_of_signal_alignment():
    freshness = assess_collector_freshness(
        latest_timestamp="2026-08-21T10:19:30+05:30",
        as_of_timestamp="2026-08-21T10:20:00+05:30",
        threshold_seconds=60,
    )
    alignment = assess_signal_alignment(
        signal_id="RBV2-1",
        signal_timestamp="2026-08-21T10:20:00+05:30",
        source_timestamp="2026-08-21T10:10:00+05:30",
        tolerance_seconds=120,
    )

    assert freshness.status == "READY"
    assert alignment.status == "STALE"
    assert alignment.reason_code == "SIGNAL_ALIGNMENT_OUTSIDE_TOLERANCE"


def test_future_source_fails_no_lookahead():
    result = assess_signal_alignment(
        signal_id="RBV2-1",
        signal_timestamp="2026-08-21T10:20:00+05:30",
        source_timestamp="2026-08-21T10:21:00+05:30",
    )

    assert result.status == "FAILED"
    assert result.no_lookahead_passed is False
    assert result.reason_code == "SOURCE_AFTER_SIGNAL"


def test_alignment_coverage_uses_exact_signal_results():
    rows = (
        assess_signal_alignment(
            signal_id="A",
            signal_timestamp="2026-08-21T10:20:00+05:30",
            source_timestamp="2026-08-21T10:19:00+05:30",
        ),
        assess_signal_alignment(
            signal_id="B",
            signal_timestamp="2026-08-21T10:20:00+05:30",
            source_timestamp="2026-08-21T10:10:00+05:30",
        ),
    )

    summary = summarize_alignment_coverage(rows)
    assert summary["total_signals"] == 2
    assert summary["aligned_signals"] == 1
    assert summary["alignment_coverage_pct"] == 50.0
    assert summary["status"] == "PARTIAL"
