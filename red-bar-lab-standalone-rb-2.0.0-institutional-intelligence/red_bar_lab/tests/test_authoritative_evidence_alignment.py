from datetime import datetime, timezone

from red_bar_lab.services.authoritative_market_evidence import (
    _safe_evidence_time,
    completed_bar_timestamps,
)


def test_completed_bar_derives_close_from_open_label():
    result = completed_bar_timestamps(
        {"observed_at": "2026-08-21T09:15:00+00:00"},
        interval_minutes=5,
    )

    assert result["bar_open_timestamp"] == "2026-08-21T09:15:00+00:00"
    assert result["bar_close_timestamp"] == "2026-08-21T09:20:00+00:00"
    assert result["observed_at"] == "2026-08-21T09:20:00+00:00"


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


def test_market_readiness_uses_true_participation_scores():
    from pathlib import Path
    import red_bar_lab.ui.pages.market_readiness as page

    source = Path(page.__file__).read_text(encoding="utf-8")
    assert 'participation.get("ce_score")' in source
    assert 'participation.get("pe_score")' in source
    assert '_display_score(bundle.get("bullish_score"))' not in source
    assert '_display_score(bundle.get("bearish_score"))' not in source
