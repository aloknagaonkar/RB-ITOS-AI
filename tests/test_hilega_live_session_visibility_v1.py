from datetime import datetime
from zoneinfo import ZoneInfo

import market_lab.hilega_historical_ui_api_v1 as mod


def _row(day: str, *, complete: bool = False):
    rows = [
        {
            "event_time": f"{day}T09:15:00+05:30",
            "checkpoint": f"{day}T09:15:00+05:30",
            "stage": "STRATEGY_DECISION_RESULT",
            "status": "COMPLETE",
            "payload": {"state_after": "PATH1_IDLE", "events_emitted": []},
        }
    ]
    if complete:
        rows.append(
            {
                "event_time": f"{day}T14:55:00+05:30",
                "checkpoint": f"{day}T14:55:00+05:30",
                "stage": "STRATEGY_TRANSITION",
                "status": "SESSION_LOCKED_1455",
                "payload": {"state_after": "SESSION_LOCKED", "events_emitted": ["SESSION_LOCKED_1455"]},
            }
        )
    return rows


def test_live_candidates_exposes_active_current_day(tmp_path, monkeypatch):
    path = tmp_path / "step-audit.jsonl"
    path.write_text("{}\n", encoding="utf-8")

    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    monkeypatch.setattr(mod, "_read_audit", lambda _p: (True, None, _row(today)))

    got = mod._live_candidates(path)
    assert len(got) == 1
    assert got[0]["session_date"] == today
    assert got[0]["source"] == "LIVE_SHADOW"
    assert got[0]["status"] == "LIVE"
    assert got[0]["evidence_level"] == "PARTIAL"


def test_live_candidates_completed_day_stays_complete(tmp_path, monkeypatch):
    path = tmp_path / "step-audit.jsonl"
    path.write_text("{}\n", encoding="utf-8")

    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    monkeypatch.setattr(mod, "_read_audit", lambda _p: (True, None, _row(today, complete=True)))

    got = mod._live_candidates(path)
    assert len(got) == 1
    assert got[0]["status"] == "COMPLETE"
    assert got[0]["evidence_level"] == "FULL"
