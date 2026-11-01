import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from market_lab.hilega_historical_ui_api_v1 import list_sessions, load_session
from market_lab.live_shadow_step_audit_v1 import ShadowStepAuditStoreV1


def _append_locked_day(path: Path, day: str):
    store = ShadowStepAuditStoreV1(path)
    cp = datetime.fromisoformat(f"{day}T14:55:00+05:30")
    store.append(
        event_time=cp, checkpoint=cp, stage="STRATEGY_DECISION",
        status="EVALUATED",
        payload={"bar_close": 23000, "state_before": "PATH1_IDLE"},
    )
    store.append(
        event_time=cp, checkpoint=cp, stage="STRATEGY_DECISION_RESULT",
        status="COMPLETE",
        payload={"state_before": "PATH1_IDLE", "state_after": "SESSION_LOCKED",
                 "events_emitted": ["SESSION_LOCKED_1455"]},
    )


def test_session_registry_prefers_phase7d_and_exposes_live_and_research(tmp_path: Path):
    root = tmp_path / "historical"
    replay = root / "hilega-milega-replay-v1"
    research = root / "hilega-milega-bullish-expansion-multisession-v1"
    live = tmp_path / "live" / "step-audit.jsonl"
    root.mkdir(parents=True)
    research.mkdir(parents=True)
    live.parent.mkdir(parents=True)

    # Rich Phase-7D day.
    p7 = root / "hilega-phase7d-2026-09-23-d4"
    p7.mkdir()
    store = ShadowStepAuditStoreV1(p7 / "step-audit.jsonl")
    cp = datetime.fromisoformat("2026-09-23T09:40:00+05:30")
    store.append(event_time=cp, checkpoint=cp, stage="STRATEGY_DECISION",
                 status="EVALUATED", payload={"bar_close": 23378, "state_before": "PATH1_IDLE"})
    store.append(event_time=cp, checkpoint=cp, stage="STRATEGY_DECISION_RESULT",
                 status="COMPLETE", payload={"state_after": "BULLISH_ACTIVE",
                 "events_emitted": ["ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21"]})
    (p7 / "source-manifest.json").write_text(json.dumps({"expiry": "2026-09-29"}))

    # Per-day replay.
    rd = replay / "2026-09-21"
    rd.mkdir(parents=True)
    rs = ShadowStepAuditStoreV1(rd / "step-audit.jsonl")
    cp2 = datetime.fromisoformat("2026-09-21T10:00:00+05:30")
    rs.append(event_time=cp2, checkpoint=cp2, stage="STRATEGY_DECISION",
              status="EVALUATED", payload={"bar_close": 23300, "state_before": "PATH1_IDLE"})
    rs.append(event_time=cp2, checkpoint=cp2, stage="STRATEGY_DECISION_RESULT",
              status="COMPLETE", payload={"state_after": "PATH1_IDLE", "events_emitted": []})

    # Completed live-shadow day.
    _append_locked_day(live, "2026-09-22")

    # 120-session summary-only day.
    with (research / "day-summary.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["session_date"])
        w.writeheader(); w.writerow({"session_date": "2026-08-25"})
    with (research / "trade-expansion-details.csv").open("w", newline="", encoding="utf-8") as fh:
        fields = ["session_date","entry_time","entry_close","exit_time","exit_close","points","source"]
        w = csv.DictWriter(fh, fieldnames=fields); w.writeheader()
        w.writerow({"session_date":"2026-08-25","entry_time":"10:15","entry_close":"23000",
                    "exit_time":"10:45","exit_close":"23025","points":"25","source":"ROUTE_A"})

    rows = list_sessions(root, replay, research, live)
    by_day = {x["session_date"]: x for x in rows}
    assert by_day["2026-09-23"]["source"] == "PHASE7D"
    assert by_day["2026-09-21"]["source"] == "SESSION_REPLAY"
    assert by_day["2026-09-22"]["source"] == "LIVE_SHADOW"
    assert by_day["2026-08-25"]["source"] == "RESEARCH_120"

    p = load_session("2026-09-23", root, replay, research, live)
    assert p["source"] == "PHASE7D"
    assert p["report_count"] == 1

    l = load_session("2026-09-22", root, replay, research, live)
    assert l["source"] == "LIVE_SHADOW"
    assert l["report_count"] == 1

    s = load_session("2026-08-25", root, replay, research, live)
    assert s["source"] == "RESEARCH_120"
    assert s["evidence_level"] == "SUMMARY"
    assert len(s["reports"]) == 2
    assert s["reports"][0]["strategy"]["selected_route"] == "ROUTE_A"
