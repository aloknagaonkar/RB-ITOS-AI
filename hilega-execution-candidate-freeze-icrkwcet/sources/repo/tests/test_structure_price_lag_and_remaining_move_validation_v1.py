import csv
import json
from pathlib import Path

from market_lab.structure_price_lag_and_remaining_move_validation_v1 import (
    build_events, build_report, load_audits, load_states
)


def _write_rows(path: Path, seq):
    fields = ["session_date", "timestamp", "horizon", "existing_horizon_state"]
    rows = []
    for t, state in seq:
        for h in ("5m", "10m", "15m"):
            rows.append({
                "session_date": "2026-01-01",
                "timestamp": f"2026-01-01T{t}:00+05:30",
                "horizon": h,
                "existing_horizon_state": state,
            })
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def test_spot_lag_and_point_targets(tmp_path: Path):
    seq = [
        ("09:30", "BEARISH"),
        ("09:35", "MIXED"),
        ("09:40", "BULLISH"),
        ("09:45", "BULLISH"),
        ("09:50", "BULLISH"),
        ("09:55", "BULLISH"),
        ("10:00", "MIXED"),
        ("10:05", "MIXED"),
        ("10:10", "MIXED"),
    ]
    rows = tmp_path / "rows.csv"
    _write_rows(rows, seq)

    spots = {
        "09:30":100, "09:35":101, "09:40":102, "09:45":101,
        "09:50":113, "09:55":132, "10:00":145, "10:05":151, "10:10":155
    }
    audits = []
    for t, _ in seq:
        audits.append({
            "timestamp": f"2026-01-01T{t}:00+05:30",
            "spot": spots[t],
            "futures_oi_direction": "BULLISH",
        })
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"session_date":"2026-01-01","rows":audits}))

    events = build_events(load_states(rows), load_audits([audit]))
    assert len(events) == 1
    e = events[0]
    assert e["price_lag_class"] == "SPOT_LAG"
    assert e["remaining_all3_candles_after_confirmation"] == 2
    assert e["hit_20pt"] is True
    assert e["candles_to_20pt"] == 2
    assert e["time_to_20pt_minutes"] == 10
    assert e["hit_20pt_within_same_all3_run"] is True
    assert e["hit_50pt"] is True
    assert e["hit_50pt_within_same_all3_run"] is False

    report = build_report(events)
    assert report["status"] == "PASS"
    assert report["threshold_optimization"] is False


def test_already_moved_class_and_censored_run(tmp_path: Path):
    seq = [
        ("09:30", "BEARISH"),
        ("09:35", "BULLISH"),
        ("09:40", "BULLISH"),
    ]
    rows = tmp_path / "rows.csv"
    _write_rows(rows, seq)

    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({
        "session_date":"2026-01-01",
        "rows":[
            {"timestamp":"2026-01-01T09:30:00+05:30","spot":100,"futures_oi_direction":"BEARISH"},
            {"timestamp":"2026-01-01T09:35:00+05:30","spot":101,"futures_oi_direction":"BULLISH"},
            {"timestamp":"2026-01-01T09:40:00+05:30","spot":105,"futures_oi_direction":"BULLISH"},
        ]
    }))

    events = build_events(load_states(rows), load_audits([audit]))
    assert len(events) == 1
    assert events[0]["price_lag_class"] == "SPOT_ALREADY_MOVED"
    assert events[0]["all3_run_censored_by_session_end"] is True
