import market_lab.historical_replay_operations_api_v1 as api


def test_launch_tolerates_popen_test_double_without_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "JOBS_ROOT", tmp_path)
    monkeypatch.setattr(api, "_active_for_date", lambda _d: None)

    class Dummy:
        pass

    monkeypatch.setattr(api.subprocess, "Popen", lambda *a, **k: Dummy())

    from datetime import date
    result = api._launch("RUN_REPLAY", date(2026, 9, 18), overwrite=True)

    assert result["status"] == "QUEUED"
    assert result["launcher_pid"] is None
    assert result["job_id"]
