import csv
import json
from pathlib import Path

from market_lab.post_confirmation_price_impulse_validation_v1 import (
    build_events,
    build_report,
    load_audits,
    load_states,
)


def test_confirmed_bullish_event_extracts_causal_impulse(tmp_path: Path):
    rows = tmp_path / "rows.csv"
    fields = ["session_date", "timestamp", "horizon", "existing_horizon_state"]
    seq = [
        ("09:30", "BEARISH"),
        ("09:35", "MIXED"),
        ("09:40", "BULLISH"),
        ("09:45", "BULLISH"),
        ("09:50", "BULLISH"),
        ("09:55", "MIXED"),
        ("10:00", "MIXED"),
        ("10:05", "MIXED"),
    ]
    data = []
    for t, s in seq:
        for h in ("5m", "10m", "15m"):
            data.append({
                "session_date": "2026-01-01",
                "timestamp": f"2026-01-01T{t}:00+05:30",
                "horizon": h,
                "existing_horizon_state": s,
            })
    with rows.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(data)

    audit = tmp_path / "audit.json"
    values = {
        "09:30": (100, 101, 100),
        "09:35": (101, 102, 101),
        "09:40": (102, 103, 102),
        "09:45": (105, 108, 104),
        "09:50": (109, 112, 107),
        "09:55": (108, 111, 107),
        "10:00": (111, 114, 108),
        "10:05": (115, 118, 109),
    }
    audit_rows = []
    for t, _ in seq:
        spot, fut, vwap = values[t]
        audit_rows.append({
            "timestamp": f"2026-01-01T{t}:00+05:30",
            "spot": spot,
            "futures_close": fut,
            "vwap": vwap,
            "futures_oi_direction": "BULLISH",
        })
    audit.write_text(json.dumps({"session_date": "2026-01-01", "rows": audit_rows}))

    events = build_events(load_states(rows), load_audits([audit]))
    assert len(events) == 1
    e = events[0]
    assert e["direction"] == "BULLISH"
    assert e["target_signed_spot_impulse_c1_c2"] == 3
    assert e["target_signed_futures_price_impulse_c1_c2"] == 5
    assert e["spot_impulse_supportive"] is True
    assert e["futures_price_impulse_supportive"] is True
    assert e["vwap_distance_improving"] is True
    assert e["signed_spot_move_plus_5m"] == 4
    report = build_report(events)
    assert report["status"] == "PASS"
    assert report["threshold_optimization"] is False


def test_futures_oi_gate_excludes_unconfirmed_event(tmp_path: Path):
    rows = tmp_path / "rows.csv"
    fields = ["session_date", "timestamp", "horizon", "existing_horizon_state"]
    seq = [("09:30", "BEARISH"), ("09:35", "BULLISH"), ("09:40", "BULLISH")]
    data = []
    for t, s in seq:
        for h in ("5m", "10m", "15m"):
            data.append({
                "session_date": "2026-01-01",
                "timestamp": f"2026-01-01T{t}:00+05:30",
                "horizon": h,
                "existing_horizon_state": s,
            })
    with rows.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(data)

    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({
        "session_date": "2026-01-01",
        "rows": [
            {"timestamp":"2026-01-01T09:30:00+05:30","spot":100,"futures_close":100,"vwap":100,"futures_oi_direction":"BEARISH"},
            {"timestamp":"2026-01-01T09:35:00+05:30","spot":101,"futures_close":101,"vwap":100,"futures_oi_direction":"BULLISH"},
            {"timestamp":"2026-01-01T09:40:00+05:30","spot":102,"futures_close":102,"vwap":100,"futures_oi_direction":"BEARISH"},
        ]
    }))
    assert build_events(load_states(rows), load_audits([audit])) == []
