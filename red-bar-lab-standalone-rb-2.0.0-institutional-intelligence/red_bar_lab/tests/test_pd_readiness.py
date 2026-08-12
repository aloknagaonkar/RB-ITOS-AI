from datetime import date, timedelta

from red_bar_lab.services.pd_readiness import build_pd_startup_readiness


def _levels(count: int):
    return [{"level_type": f"PD{rank}_315"} for rank in range(1, count + 1)]


def test_pd_readiness_is_ready_with_ten_sessions_and_levels():
    trading_date = date(2026, 8, 12)
    dates = [trading_date - timedelta(days=rank) for rank in range(1, 11)] + [trading_date]
    result = build_pd_startup_readiness(dates, _levels(10), trading_date)
    assert result["status"] == "READY"
    assert result["prior_sessions"] == 10
    assert result["pd_levels"] == 10
    assert result["signal_scanning_ready"] is True


def test_pd_readiness_reports_backfill_when_history_is_short():
    trading_date = date(2026, 8, 12)
    dates = [trading_date - timedelta(days=rank) for rank in range(1, 4)] + [trading_date]
    result = build_pd_startup_readiness(dates, _levels(3), trading_date)
    assert result["status"] == "BACKFILLING"
    assert result["prior_sessions"] == 3
    assert result["signal_scanning_ready"] is False


def test_pd_readiness_reports_partial_when_level_creation_is_incomplete():
    trading_date = date(2026, 8, 12)
    dates = [trading_date - timedelta(days=rank) for rank in range(1, 11)] + [trading_date]
    result = build_pd_startup_readiness(dates, _levels(8), trading_date)
    assert result["status"] == "PARTIAL"
    assert result["pd_levels"] == 8
    assert result["missing_pd_levels"] == ("PD9_315", "PD10_315")
