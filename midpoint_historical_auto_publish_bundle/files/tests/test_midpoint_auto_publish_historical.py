from datetime import datetime
from pathlib import Path

def _load_script():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts/midpoint_auto_publish_historical.py"
    spec = importlib.util.spec_from_file_location("midpoint_auto_publish", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_only_prior_unpublished_audit_dates_are_eligible(tmp_path, monkeypatch):
    module = _load_script()
    monkeypatch.setattr(module, "REPLAY_ROOT", tmp_path)
    (tmp_path / "2026-09-29").mkdir()
    rows = [
        {"session_date": "2026-09-28"},
        {"event_timestamp": "2026-09-29T09:20:00+05:30"},
        {"session_date": "2026-09-30"},
        {"session_date": "2026-10-01"},
    ]
    manifest = {"sessions": [{"session_date": "2026-09-28"}]}
    result = module.eligible_missing_dates(
        rows,
        manifest,
        now=datetime.fromisoformat("2026-10-01T20:00:00+05:30"),
    )
    assert result == ["2026-09-30"]


def test_today_becomes_eligible_only_on_next_ist_day(tmp_path, monkeypatch):
    module = _load_script()
    monkeypatch.setattr(module, "REPLAY_ROOT", tmp_path)
    rows = [{"session_date": "2026-10-01"}]
    assert module.eligible_missing_dates(
        rows, {"sessions": []},
        now=datetime.fromisoformat("2026-10-01T23:59:00+05:30"),
    ) == []
    assert module.eligible_missing_dates(
        rows, {"sessions": []},
        now=datetime.fromisoformat("2026-10-02T00:01:00+05:30"),
    ) == ["2026-10-01"]


def test_historical_ui_reads_atomic_manifest_sessions():
    source = (
        Path(__file__).resolve().parents[1]
        / "backend/market_lab/midpoint_strategy/live_shadow_ui.py"
    ).read_text()
    assert 'HIST_MANIFEST = HIST_ROOT / "manifest.json"' in source
