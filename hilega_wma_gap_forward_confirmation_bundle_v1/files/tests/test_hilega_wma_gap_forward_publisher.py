import csv
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/hilega_wma_gap_forward_publisher.py"
SPEC = importlib.util.spec_from_file_location("hilega_wma_forward_test", SCRIPT)
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def test_completed_sessions_require_processed_directional_cutoff(tmp_path):
    audit = tmp_path / "audit.jsonl"
    rows = [
        {"stage":"DIRECTIONAL_SESSION_CUTOFF","status":"WAITING","payload":{"cutoff_timestamp":"2026-10-01T14:55:00+05:30"}},
        {"stage":"DIRECTIONAL_SESSION_CUTOFF","status":"PROCESSED","payload":{"cutoff_timestamp":"2026-10-02T14:55:00+05:30"}},
    ]
    audit.write_text("\n".join(json.dumps(x) for x in rows)+"\n")
    assert m.completed_live_sessions(audit) == ["2026-10-02"]


def test_session_publication_is_immutable_and_indexes_are_rebuilt(tmp_path, monkeypatch):
    output = tmp_path / "forward"; day = "2026-10-02"
    result = {"trade_id":"t1","session_date":day,"direction":"BULLISH","canonical_points":10,"candidate_points":8,"candidate_decision":"ENTRY"}
    monkeypatch.setattr(m, "generate_session", lambda *_: ([result], [], []))
    monkeypatch.setattr(m, "FROZEN_ROOT", tmp_path / "frozen")
    first = m.publish_session(day, tmp_path / "cache", output)
    second = m.publish_session(day, tmp_path / "cache", output)
    report = m.rebuild_indexes(output)
    assert first["status"] == "PUBLISHED"
    assert second["status"] == "ALREADY_PUBLISHED"
    assert report["selected_dates"] == [day]
    assert report["candidate_points"] == 8
    assert len(m.csv_rows(output / "trade-results.csv")) == 1


def test_frozen_dates_are_never_selected_for_forward_publication(tmp_path, monkeypatch):
    frozen = tmp_path / "frozen"
    write_csv(frozen / "trade-results.csv", [{"session_date":"2026-10-01"}])
    audit = tmp_path / "audit.jsonl"
    audit.write_text("\n".join(json.dumps({"stage":"DIRECTIONAL_SESSION_CUTOFF","status":"PROCESSED","payload":{"cutoff_timestamp":f"{day}T14:55:00+05:30"}}) for day in ("2026-10-01","2026-10-02"))+"\n")
    monkeypatch.setattr(m, "FROZEN_ROOT", frozen)
    monkeypatch.setattr(m, "publish_session", lambda day,*_: {"session_date":day,"status":"PUBLISHED"})
    monkeypatch.setattr(m, "rebuild_indexes", lambda *_: {"forward_sessions":1})
    result = m.run_once(audit, tmp_path / "cache", tmp_path / "forward")
    assert [x["session_date"] for x in result["published"]] == ["2026-10-02"]


def test_historical_builder_prefers_separate_forward_session(tmp_path, monkeypatch):
    import market_lab.hilega_wma_gap_historical_v1 as module
    frozen = tmp_path / "frozen"; forward = tmp_path / "forward"; day = "2026-10-06"
    write_csv(forward / "trade-results.csv", [{
        "trade_id":"forward-one", "session_date":day, "direction":"BULLISH",
        "route":"ROUTE_A", "entry_timestamp":f"{day}T10:00:00+05:30",
        "entry_price":"100", "exit_timestamp":f"{day}T10:20:00+05:30",
        "exit_price":"110", "canonical_points":"10", "mfe_points":"20",
        "candidate_decision":"NO_ENTRY", "candidate_points":"",
    }])
    monkeypatch.setattr(module, "ROOT", frozen)
    monkeypatch.setattr(module, "FORWARD_ROOT", forward)
    result = module.build_wma_gap_session(day)
    assert result["evidence_cohort"] == "NEW_FORWARD_CONFIRMATION"
