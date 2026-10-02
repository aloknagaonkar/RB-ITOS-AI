from datetime import date
from types import SimpleNamespace

from market_lab.historical_replay_data_v1 import (
    _safe_name,
    option_cache_path,
    readiness,
)


def test_safe_option_cache_name_is_stable():
    assert _safe_name("NSE_FO|ABC") == _safe_name("NSE_FO|ABC")
    assert _safe_name("NSE_FO|ABC") != _safe_name("NSE_FO|XYZ")


def test_option_cache_path_is_isolated(tmp_path):
    path = option_cache_path(date(2026, 9, 18), "NSE_FO|ABC", tmp_path)
    assert "2026-09-18" in str(path)
    assert "options-1m" in str(path)
    assert "NSE_FO|ABC" not in path.name


def test_readiness_reports_on_demand_option_data(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "market_lab.historical_replay_data_v1.snapshot_count",
        lambda engine, session_date: 123,
    )
    monkeypatch.setattr(
        "market_lab.historical_replay_data_v1.snapshot_span",
        lambda engine, session_date: (
            "2026-09-18T09:15:00+05:30",
            "2026-09-18T15:30:00+05:30",
        ),
    )
    out = readiness(date(2026, 9, 18), engine=SimpleNamespace(), cache_root=tmp_path)
    assert out["checkpoint_analysis_ready"] is True
    assert out["full_replay_prerequisites_ready"] is False
    option = next(item for item in out["datasets"] if item["name"] == "EXACT_OPTION_1M")
    assert option["status"] == "ON_DEMAND"


def test_readiness_recognizes_cached_futures(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "market_lab.historical_replay_data_v1.snapshot_count",
        lambda engine, session_date: 123,
    )
    monkeypatch.setattr(
        "market_lab.historical_replay_data_v1.snapshot_span",
        lambda engine, session_date: (None, None),
    )
    path = tmp_path / "2026-09-18" / "futures-1m.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"candles":[{"timestamp":"x"}]}')

    out = readiness(date(2026, 9, 18), engine=SimpleNamespace(), cache_root=tmp_path)
    assert out["full_replay_prerequisites_ready"] is True
