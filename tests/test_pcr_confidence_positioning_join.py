import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

from market_lab.pcr_confidence_positioning_join import analyze


def _write_csv(path: Path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def test_joint_report_uses_confirmed_frozen_features_and_timing(tmp_path):
    spec = tmp_path / "spec.json"
    val = tmp_path / "val.json"
    evidence = tmp_path / "evidence.csv"
    pos = tmp_path / "positioning.csv"

    spec.write_text(json.dumps({
        "status": "AVAILABLE",
        "bearish": {"frozen_train_buckets": [
            {"feature": "fixed_pcr_change_5m", "train_cut_points": [-0.03, -0.02, -0.01]},
            {"feature": "fixed_pcr_change_15m", "train_cut_points": [-0.06, -0.04, -0.02]},
        ]},
        "bullish": {"frozen_train_buckets": [
            {"feature": "fixed_pcr_change_5m", "train_cut_points": [0.01, 0.02, 0.03]},
            {"feature": "fixed_pcr_change_15m", "train_cut_points": [0.02, 0.04, 0.06]},
        ]},
    }), encoding="utf-8")
    val.write_text(json.dumps({
        "status": "AVAILABLE",
        "bearish": {"features": [
            {"feature": "fixed_pcr_change_5m", "expected_monotonic": "INCREASING", "expected_direction_confirmed": True},
            {"feature": "fixed_pcr_change_15m", "expected_monotonic": "INCREASING", "expected_direction_confirmed": True},
        ]},
        "bullish": {"features": [
            {"feature": "fixed_pcr_change_5m", "expected_monotonic": "DECREASING", "expected_direction_confirmed": True},
            {"feature": "fixed_pcr_change_15m", "expected_monotonic": "DECREASING", "expected_direction_confirmed": True},
        ]},
    }), encoding="utf-8")

    fields = [
        "session_date","timestamp","spot","forward_change_5m","forward_change_15m","forward_change_30m",
        "moving_pcr_change_5m","moving_pcr_change_15m","moving_pcr_change_30m",
        "fixed_pcr","moving_pcr","full_pcr","fixed_moving_pcr_spread",
        "fixed_pcr_change_1m","fixed_pcr_change_5m","fixed_pcr_change_15m","fixed_pcr_change_30m",
        "moving_pcr_change_1m","full_pcr_change_1m","full_pcr_change_5m","full_pcr_change_15m","full_pcr_change_30m",
        "fixed_call_oi_change_pct","fixed_put_oi_change_pct","moving_call_oi_change_pct","moving_put_oi_change_pct",
        "full_call_oi_change_pct","full_put_oi_change_pct","atm_divergence_points"
    ]
    rows = []
    base = datetime.fromisoformat("2026-01-01T09:15:00+05:30")
    for i in range(46):
        dt = base + timedelta(minutes=i)
        minute = 15 + i
        ts = dt.isoformat()
        row = {k: 0 for k in fields}
        row.update(session_date="2026-01-01", timestamp=ts, spot=100 + minute)
        row.update(forward_change_5m=-1, forward_change_15m=-2, forward_change_30m=-3)
        row.update(moving_pcr_change_5m=1, moving_pcr_change_15m=1, moving_pcr_change_30m=1)
        row.update(fixed_pcr_change_5m=-0.005, fixed_pcr_change_15m=-0.01)
        if dt.hour == 9 and dt.minute == 45:
            row.update(moving_pcr_change_5m=-1, moving_pcr_change_15m=-1, moving_pcr_change_30m=1)
        rows.append(row)
    _write_csv(evidence, fields, rows)

    pfields = ["session_date","timestamp","strike","strike_offset","combined_5m","ce_5m_state","pe_5m_state"]
    prows = []
    for off in range(6):
        prows.append({
            "session_date":"2026-01-01",
            "timestamp":f"2026-01-01T09:{45+off:02d}:00+05:30",
            "strike":"100","strike_offset":"0",
            "combined_5m":"STRONG_BEARISH" if off == 1 else "MIXED",
            "ce_5m_state":"SHORT_BUILDUP","pe_5m_state":"LONG_BUILDUP",
        })
    _write_csv(pos, pfields, prows)

    result = analyze(spec, val, evidence, pos)
    b = result["directions"]["bearish"]
    assert [x["feature"] for x in b["confirmed_severity_features"]] == [
        "fixed_pcr_change_5m", "fixed_pcr_change_15m"
    ]
    assert b["stage_2_event_count"] == 1
    event = b["events"][0]
    assert event["confidence_tier"] == "VERY_HIGH"
    assert event["first_confirmation_offset_minutes"] == 1
    assert event["confirmation_offset_group"] == "T_PLUS_1"
    assert b["severity_timing_matrix"]["VERY_HIGH"]["T_PLUS_1"]["event_count"] == 1


def test_unconfirmed_validation_features_are_excluded(tmp_path):
    spec = tmp_path / "spec.json"
    val = tmp_path / "val.json"
    evidence = tmp_path / "e.csv"
    pos = tmp_path / "p.csv"
    spec.write_text(json.dumps({
        "status":"AVAILABLE",
        "bearish":{"frozen_train_buckets":[
            {"feature":"fixed_pcr_change_5m","train_cut_points":[-3,-2,-1]},
            {"feature":"moving_pcr_change_15m","train_cut_points":[-3,-2,-1]},
        ]},
        "bullish":{"frozen_train_buckets":[]},
    }), encoding="utf-8")
    val.write_text(json.dumps({
        "status":"AVAILABLE",
        "bearish":{"features":[
            {"feature":"fixed_pcr_change_5m","expected_monotonic":"INCREASING","expected_direction_confirmed":True},
            {"feature":"moving_pcr_change_15m","expected_monotonic":"DECREASING","expected_direction_confirmed":False},
        ]},
        "bullish":{"features":[]},
    }), encoding="utf-8")
    # Empty-looking files still need valid headers for loaders.
    fields=[
        "session_date","timestamp","spot","forward_change_5m","forward_change_15m","forward_change_30m",
        "moving_pcr_change_5m","moving_pcr_change_15m","moving_pcr_change_30m",
        "fixed_pcr","moving_pcr","full_pcr","fixed_moving_pcr_spread","fixed_pcr_change_1m","fixed_pcr_change_5m",
        "fixed_pcr_change_15m","fixed_pcr_change_30m","moving_pcr_change_1m","full_pcr_change_1m","full_pcr_change_5m",
        "full_pcr_change_15m","full_pcr_change_30m","fixed_call_oi_change_pct","fixed_put_oi_change_pct",
        "moving_call_oi_change_pct","moving_put_oi_change_pct","full_call_oi_change_pct","full_put_oi_change_pct","atm_divergence_points"
    ]
    row={k:0 for k in fields}; row.update(session_date="2026-01-01",timestamp="2026-01-01T10:00:00+05:30",spot=100)
    _write_csv(evidence, fields, [row])
    _write_csv(pos,["session_date","timestamp","strike","strike_offset","combined_5m","ce_5m_state","pe_5m_state"],[])
    result=analyze(spec,val,evidence,pos)
    names=[x["feature"] for x in result["directions"]["bearish"]["confirmed_severity_features"]]
    assert names == ["fixed_pcr_change_5m"]
