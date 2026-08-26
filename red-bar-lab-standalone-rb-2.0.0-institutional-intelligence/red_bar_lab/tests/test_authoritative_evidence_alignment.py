from datetime import datetime, timezone

from red_bar_lab.services.authoritative_market_evidence import (
    _authoritative_evaluation_time,
    _safe_evidence_time,
    completed_bar_timestamps,
)


def test_completed_bar_derives_close_without_relabeling_observation():
    result = completed_bar_timestamps(
        {"observed_at": "2026-08-21T09:15:00+00:00"},
        interval_minutes=5,
    )

    assert result["bar_open_timestamp"] == "2026-08-21T09:15:00+00:00"
    assert result["bar_close_timestamp"] == "2026-08-21T09:20:00+00:00"
    assert result["observed_at"] == "2026-08-21T09:15:00+00:00"


def test_completed_bar_preserves_explicit_close_without_double_shift():
    result = completed_bar_timestamps(
        {
            "bar_open_timestamp": "2026-08-21T09:15:00+00:00",
            "bar_close_timestamp": "2026-08-21T09:20:00+00:00",
            "observed_at": "2026-08-21T09:20:00+00:00",
        },
        interval_minutes=5,
    )

    assert result["bar_close_timestamp"] == "2026-08-21T09:20:00+00:00"
    assert result["observed_at"] == "2026-08-21T09:20:00+00:00"


def test_safe_evidence_time_uses_completed_bar_closes():
    result = _safe_evidence_time(
        {
            "option_timestamp": "2026-08-21T09:22:00+00:00",
            "futures_bar_close_timestamp": "2026-08-21T09:20:00+00:00",
            "underlying_bar_close_timestamp": "2026-08-21T09:25:00+00:00",
        }
    )

    assert result == datetime(2026, 8, 21, 9, 20, tzinfo=timezone.utc).isoformat()


def test_authoritative_bundle_uses_actual_evaluation_after_long_cycle():
    cycle_started = datetime(2026, 8, 25, 6, 8, tzinfo=timezone.utc)
    evaluated = datetime(2026, 8, 25, 6, 14, 45, tzinfo=timezone.utc)

    assert _authoritative_evaluation_time(
        cycle_started,
        evaluated_at=evaluated,
    ) == evaluated


def test_authoritative_bundle_never_moves_before_cycle_start():
    cycle_started = datetime(2026, 8, 25, 6, 15, tzinfo=timezone.utc)
    stale_clock = datetime(2026, 8, 25, 6, 14, 59, tzinfo=timezone.utc)

    assert _authoritative_evaluation_time(
        cycle_started,
        evaluated_at=stale_clock,
    ) == cycle_started


def test_market_readiness_uses_true_participation_scores():
    from pathlib import Path
    import red_bar_lab.ui.pages.market_readiness as page

    source = Path(page.__file__).read_text(encoding="utf-8")
    assert 'participation.get("ce_score")' in source
    assert 'participation.get("pe_score")' in source
    assert '_display_score(bundle.get("bullish_score"))' not in source
    assert '_display_score(bundle.get("bearish_score"))' not in source
