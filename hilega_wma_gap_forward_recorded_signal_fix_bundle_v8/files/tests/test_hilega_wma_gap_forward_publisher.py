import csv
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/hilega_wma_gap_forward_publisher.py"
SPEC = importlib.util.spec_from_file_location("hilega_wma_forward_test", SCRIPT)
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)
IST = ZoneInfo("Asia/Kolkata")


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
    monkeypatch.setattr(m, "ensure_recorded_cache", lambda *_: {"source":"TEST","minutes":375,"five_minute_bars":75})
    monkeypatch.setattr(m, "FROZEN_ROOT", tmp_path / "frozen")
    first = m.publish_session(day, tmp_path / "cache", output)
    second = m.publish_session(day, tmp_path / "cache", output)
    report = m.rebuild_indexes(output)
    assert first["status"] == "PUBLISHED"
    assert second["status"] == "ALREADY_PUBLISHED"
    assert report["selected_dates"] == [day]
    assert report["candidate_points"] == 8
    assert len(m.csv_rows(output / "trade-results.csv")) == 1


def test_zero_trade_completed_session_is_published(tmp_path, monkeypatch):
    day = "2026-10-05"; output = tmp_path / "forward"
    monkeypatch.setattr(m, "ensure_recorded_cache", lambda *_: {
        "source":"TEST", "minutes":374, "five_minute_bars":74,
        "strategy_five_minute_bars":69,
    })
    monkeypatch.setattr(m, "generate_session", lambda *_: ([], [], []))
    monkeypatch.setattr(m, "FROZEN_ROOT", tmp_path / "frozen")
    result = m.publish_session(day, tmp_path / "cache", output)
    assert result["status"] == "PUBLISHED"
    assert result["signals"] == 0
    assert result["candidate_entries"] == 0
    assert (output / "sessions" / day / "manifest.json").is_file()


def test_recorded_live_completed_trades_are_authoritative(monkeypatch):
    import market_lab.hilega_historical_ui_api_v1 as api
    day = "2026-10-05"
    reports = [{
        "checkpoint": f"{day}T09:25:00+05:30",
        "transitions": [{
            "event_type": "ENTRY_OPENING_BULLISH_CONFIRMED",
            "event_time": f"{day}T09:25:00+05:30", "price": 100,
        }],
    }, {
        "checkpoint": f"{day}T09:35:00+05:30",
        "transitions": [{
            "event_type": "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21",
            "event_time": f"{day}T09:35:00+05:30", "price": 112,
        }],
    }]
    monkeypatch.setattr(api, "load_session", lambda _: {"reports": reports})
    bars = [SimpleNamespace(
        ts=datetime.fromisoformat(f"{day}T09:30:00+05:30").astimezone(IST),
        high=115, low=98,
    )]
    trades, audit = m.recorded_live_completed_trades(day, {}, bars)
    assert len(trades) == 1
    assert trades[0]["captured_points"] == 12
    assert trades[0]["mfe_points"] == 15
    assert audit == {
        "source": "IMMUTABLE_RECORDED_LIVE_DECISION_AUDIT",
        "recorded_live_signals": 1,
        "recorded_live_completed": 1,
        "recorded_live_unresolved": 0,
    }


def test_rebuild_forward_session_preserves_superseded_copy(tmp_path, monkeypatch):
    day = "2026-10-05"
    output = tmp_path / "forward"
    old = output / "sessions" / day
    old.mkdir(parents=True)
    (old / "manifest.json").write_text('{"signals":0}')
    monkeypatch.setattr(m, "publish_session", lambda *args: {"status":"PUBLISHED", "session_date":day})
    monkeypatch.setattr(m, "rebuild_indexes", lambda *_: {})
    result = m.rebuild_forward_session(day, tmp_path / "cache", output, tmp_path / "evidence")
    assert result["status"] == "PUBLISHED"
    assert list((output / "superseded").glob(f"{day}-*/manifest.json"))


def test_frozen_dates_are_never_selected_for_forward_publication(tmp_path, monkeypatch):
    frozen = tmp_path / "frozen"
    write_csv(frozen / "trade-results.csv", [{"session_date":"2026-10-01"}])
    audit = tmp_path / "audit.jsonl"
    audit.write_text("\n".join(json.dumps({"stage":"DIRECTIONAL_SESSION_CUTOFF","status":"PROCESSED","payload":{"cutoff_timestamp":f"{day}T14:55:00+05:30"}}) for day in ("2026-10-01","2026-10-02"))+"\n")
    monkeypatch.setattr(m, "FROZEN_ROOT", frozen)
    (frozen / "report.json").write_text(json.dumps({"sessions":{"last_session":"2026-10-01"}}))
    monkeypatch.setattr(m, "publish_session", lambda day,*_: {"session_date":day,"status":"PUBLISHED"})
    monkeypatch.setattr(m, "rebuild_indexes", lambda *_: {"forward_sessions":1})
    result = m.run_once(audit, tmp_path / "cache", tmp_path / "forward")
    assert [x["session_date"] for x in result["published"]] == ["2026-10-02"]


def test_frozen_zero_trade_dates_are_excluded_by_report_cutoff(tmp_path, monkeypatch):
    frozen = tmp_path / "frozen"; frozen.mkdir()
    (frozen / "report.json").write_text(json.dumps({"sessions":{"last_session":"2026-10-01"}}))
    audit = tmp_path / "audit.jsonl"
    audit.write_text("\n".join(json.dumps({"stage":"DIRECTIONAL_SESSION_CUTOFF","status":"PROCESSED","payload":{"cutoff_timestamp":f"{day}T14:55:00+05:30"}}) for day in ("2026-09-24","2026-10-02"))+"\n")
    monkeypatch.setattr(m, "FROZEN_ROOT", frozen)
    monkeypatch.setattr(m, "publish_session", lambda day,*_: {"session_date":day,"status":"PUBLISHED"})
    monkeypatch.setattr(m, "rebuild_indexes", lambda *_: {"forward_sessions":1})
    result = m.run_once(audit, tmp_path / "cache", tmp_path / "forward")
    assert [x["session_date"] for x in result["published"]] == ["2026-10-02"]


def test_final_recorded_revision_is_selected(monkeypatch, tmp_path):
    path = tmp_path / "2026-10-05.jsonl"; path.write_text("placeholder")
    base = {"session_date":"2026-10-05", "instrument_key":"NSE_INDEX|Nifty 50", "interval_seconds":60,
            "timestamp":"2026-10-05T09:15:00+05:30", "open":100, "high":102, "low":99, "close":101, "volume":10}
    records = [
        {"kind":"underlying", "status":"OK", "response":[base]},
        {"kind":"underlying", "status":"OK", "response":[{**base, "close":101.5, "high":102.5}]},
    ]
    import market_lab.hilega_market_evidence_v1 as evidence
    monkeypatch.setattr(evidence, "verify_journal", lambda _: records)
    rows, diagnostics = m.final_recorded_minutes("2026-10-05", path)
    assert rows[0]["close"] == 101.5
    assert diagnostics["revised_minutes"] == 1
    assert diagnostics["resolution_policy"].startswith("FINAL_RECORDED_REVISION")


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
