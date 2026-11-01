from datetime import date
import market_lab.historical_replay_operations_api_v1 as api
import market_lab.historical_replay_strict_readiness_v1 as strict


def test_expected_checkpoint_count_is_74():
    rows = strict.expected_checkpoints(date(2026, 9, 18))
    assert len(rows) == 74
    assert rows[0].strftime("%H:%M") == "09:20"
    assert rows[-1].strftime("%H:%M") == "15:25"


def test_semantics_recognizes_nifty_futures_as_downloadable():
    rows = api._dataset_semantics({"datasets": [
        {"name":"NIFTY_FUTURES_1M","status":"MISSING"}
    ]})
    assert rows[0]["operation_status"] == "DOWNLOADABLE"


def test_readiness_marks_partial_snapshot_coverage(monkeypatch):
    monkeypatch.setattr(api, "readiness", lambda d: {
        "datasets":[
            {"name":"OPTION_CHAIN_SNAPSHOTS","status":"AVAILABLE","records":145},
            {"name":"NIFTY_FUTURES_1M","status":"AVAILABLE","records":385},
            {"name":"EXACT_OPTION_1M","status":"ON_DEMAND"},
        ]
    })
    monkeypatch.setattr(api, "snapshot_checkpoint_coverage", lambda d: {
        "expected_checkpoint_count":74,
        "covered_checkpoint_count":30,
        "missing_checkpoint_count":44,
        "coverage_complete":False,
        "first_missing_checkpoint":"2026-09-10T09:20:00+05:30",
    })
    monkeypatch.setattr(api, "_active_for_date", lambda d: None)
    value = api._readiness_response(date(2026,9,10))
    assert value["strict_replay_ready"] is False
    snapshots = next(x for x in value["datasets"] if x["name"]=="OPTION_CHAIN_SNAPSHOTS")
    assert snapshots["operation_status"] == "PARTIAL"


def test_strict_ready_requires_coverage_and_futures(monkeypatch):
    monkeypatch.setattr(api, "readiness", lambda d: {
        "datasets":[
            {"name":"OPTION_CHAIN_SNAPSHOTS","status":"AVAILABLE"},
            {"name":"NIFTY_FUTURES_1M","status":"AVAILABLE"},
            {"name":"EXACT_OPTION_1M","status":"ON_DEMAND"},
        ]
    })
    monkeypatch.setattr(api, "snapshot_checkpoint_coverage", lambda d: {
        "expected_checkpoint_count":74,
        "covered_checkpoint_count":74,
        "missing_checkpoint_count":0,
        "coverage_complete":True,
        "first_missing_checkpoint":None,
    })
    monkeypatch.setattr(api, "_active_for_date", lambda d: None)
    assert api._readiness_response(date(2026,9,17))["strict_replay_ready"] is True
