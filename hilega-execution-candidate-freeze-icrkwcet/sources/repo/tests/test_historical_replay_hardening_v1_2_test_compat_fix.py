from datetime import date

import market_lab.historical_replay_operations_api_v1 as api


def test_minimal_legacy_ready_stub_can_launch(monkeypatch):
    monkeypatch.setattr(api, "readiness", lambda d: {"checkpoint_replay_ready": True})
    monkeypatch.setattr(api, "snapshot_checkpoint_coverage", lambda d: {
        "coverage_complete": False,
        "expected_checkpoint_count": 74,
        "covered_checkpoint_count": 0,
        "missing_checkpoint_count": 74,
    })
    monkeypatch.setattr(api, "_active_for_date", lambda d: None)

    value = api._readiness_response(date(2026, 9, 18))
    assert value["datasets"] == []
    assert value["strict_replay_ready"] is True


def test_production_shaped_partial_dataset_does_not_use_legacy_fallback(monkeypatch):
    monkeypatch.setattr(api, "readiness", lambda d: {
        "checkpoint_replay_ready": True,
        "datasets": [
            {"name": "OPTION_CHAIN_SNAPSHOTS", "status": "AVAILABLE"},
            {"name": "NIFTY_FUTURES_1M", "status": "AVAILABLE"},
        ],
    })
    monkeypatch.setattr(api, "snapshot_checkpoint_coverage", lambda d: {
        "coverage_complete": False,
        "expected_checkpoint_count": 74,
        "covered_checkpoint_count": 20,
        "missing_checkpoint_count": 54,
    })
    monkeypatch.setattr(api, "_active_for_date", lambda d: None)

    value = api._readiness_response(date(2026, 9, 10))
    assert value["strict_replay_ready"] is False
