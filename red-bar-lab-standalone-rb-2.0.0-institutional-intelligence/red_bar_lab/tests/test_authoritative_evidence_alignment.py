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
    """CE/PE pressure must be measured, not read off a precomputed bundle.

    The Trade Evidence page used to render its own participation panel and
    this guard pinned it there. That inline renderer became unreachable when
    9821ef0 retired the tab that called it, and it has since been deleted --
    the panels the page installs (market_at_a_glance and
    market_readiness_score_explanation) own the scores now. The invariant is
    unchanged: pressure is derived from the participation summary's
    ce_score/pe_score, never from a bundle's bullish_score/bearish_score.
    """
    from pathlib import Path

    ui_dir = Path(__file__).resolve().parents[1] / "ui"
    panels = (
        ui_dir / "market_at_a_glance.py",
        ui_dir / "market_readiness_score_explanation.py",
    )

    for panel in panels:
        source = panel.read_text(encoding="utf-8")
        assert 'summary.get("ce_score")' in source
        assert 'summary.get("pe_score")' in source

    for path in (*panels, ui_dir / "pages" / "market_readiness.py"):
        source = path.read_text(encoding="utf-8")
        assert 'bundle.get("bullish_score")' not in source
        assert 'bundle.get("bearish_score")' not in source
