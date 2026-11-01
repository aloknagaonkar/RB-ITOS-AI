from pathlib import Path
import json
from market_lab.midpoint_strategy import live_shadow_ui as ui

def test_recent_two_midpoint_sessions():
    rows=[{"session_date":"2026-09-24","event_id":"a"},{"session_date":"2026-09-25","event_id":"b"},{"session_date":"2026-09-28","event_id":"c"}]
    assert [x["event_id"] for x in ui._recent_rows(rows,2)]==["b","c"]
    assert ui._recent_session_days(rows,2)==["2026-09-28","2026-09-25"]

def test_midpoint_historical_manifest_and_session(tmp_path: Path, monkeypatch):
    root=tmp_path/"hist"; day=root/"2026-08-25"; day.mkdir(parents=True)
    row={"event_id":"evt1","session_date":"2026-08-25","event_timestamp":"2026-08-25T09:30:00+05:30","event_type":"BOUNDARY_BREAK","family":"B","direction":"BULLISH"}
    (day/"audit.jsonl").write_text(json.dumps(row)+"\n")
    (root/"manifest.json").write_text(json.dumps({"model":"MIDPOINT_UI_REPLAY_MANIFEST_V1","sessions":[{"session_date":"2026-08-25","block":"B4","event_count":1,"source":"V57_PARITY_PROVEN_REPLAY","status":"AVAILABLE"}]}))
    monkeypatch.setattr(ui,"HIST_ROOT",root); monkeypatch.setattr(ui,"HIST_MANIFEST",root/"manifest.json")
    assert ui.historical_sessions()["count"]==1
    replay=ui.historical_session("2026-08-25")
    assert replay["mode"]=="HISTORICAL_REPLAY"
    assert replay["timeline"][0]["event_id"]=="evt1"
