import json
from pathlib import Path

from market_lab.midpoint_strategy import live_shadow_ui as ui


def test_fresh_a_display_owner_does_not_mutate_raw_family():
    row = {
        "event_id": "x",
        "session_date": "2026-08-25",
        "event_timestamp": "2026-08-25T09:30:00+05:30",
        "event_type": "BOUNDARY_OWNER_OTHER",
        "family": "B",
        "reason": "FRESH_CANDIDATE_A_AT_BOUNDARY",
    }
    projected = ui._timeline_projection([row])[0]
    assert projected["family"] == "B"
    assert projected["display_owner"] == "FRESH A"


def test_historical_session_merges_full_day_minutes_with_events(tmp_path: Path, monkeypatch):
    root = tmp_path / "hist"
    day = root / "2026-08-25"
    day.mkdir(parents=True)

    event = {
        "event_id": "evt1",
        "session_date": "2026-08-25",
        "event_timestamp": "2026-08-25T09:16:00+05:30",
        "event_type": "MIDPOINT_BREAK",
        "family": "B",
        "direction": "BULLISH",
        "reason": "ONE_MINUTE_CLOSE_BEYOND_MIDPOINT",
    }
    (day / "audit.jsonl").write_text(json.dumps(event) + "\n")

    minutes = [
        {
            "session_date": "2026-08-25",
            "timestamp": "2026-08-25T09:15:00+05:30",
            "underlying_open": 1,
            "underlying_high": 2,
            "underlying_low": 0.5,
            "underlying_close": 1.5,
            "futures_close": 101,
            "futures_vwap": 100.5,
            "data_status": "BOTH",
        },
        {
            "session_date": "2026-08-25",
            "timestamp": "2026-08-25T09:16:00+05:30",
            "underlying_open": 1.5,
            "underlying_high": 2.1,
            "underlying_low": 1.4,
            "underlying_close": 2,
            "futures_close": 102,
            "futures_vwap": 101,
            "data_status": "BOTH",
        },
    ]
    (day / "minutes.jsonl").write_text(
        "".join(json.dumps(x) + "\n" for x in minutes)
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "model": "MIDPOINT_UI_REPLAY_MANIFEST_V1",
                "sessions": [
                    {
                        "session_date": "2026-08-25",
                        "block": "B4",
                        "event_count": 1,
                        "minute_count": 2,
                        "source": "V57_PARITY_PROVEN_REPLAY",
                        "status": "AVAILABLE",
                    }
                ],
            }
        )
    )

    monkeypatch.setattr(ui, "HIST_ROOT", root)
    monkeypatch.setattr(ui, "HIST_MANIFEST", root / "manifest.json")

    replay = ui.historical_session("2026-08-25")
    assert replay["mode"] == "HISTORICAL_REPLAY"
    assert replay["minute_count"] == 2
    assert len(replay["minutes"]) == 2
    assert replay["minutes"][0]["events"] == []
    assert replay["minutes"][1]["events"][0]["event_id"] == "evt1"


def test_missing_minutes_remains_backward_compatible(tmp_path: Path, monkeypatch):
    root = tmp_path / "hist"
    day = root / "2026-08-25"
    day.mkdir(parents=True)
    event = {
        "event_id": "evt1",
        "session_date": "2026-08-25",
        "event_timestamp": "2026-08-25T09:30:00+05:30",
        "event_type": "BOUNDARY_BREAK",
        "family": "B",
    }
    (day / "audit.jsonl").write_text(json.dumps(event) + "\n")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "model": "MIDPOINT_UI_REPLAY_MANIFEST_V1",
                "sessions": [
                    {
                        "session_date": "2026-08-25",
                        "event_count": 1,
                        "source": "V57_PARITY_PROVEN_REPLAY",
                        "status": "EVENTS_ONLY",
                    }
                ],
            }
        )
    )
    monkeypatch.setattr(ui, "HIST_ROOT", root)
    monkeypatch.setattr(ui, "HIST_MANIFEST", root / "manifest.json")
    replay = ui.historical_session("2026-08-25")
    assert replay["minute_count"] == 0
    assert replay["timeline"][0]["event_id"] == "evt1"
