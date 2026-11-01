import csv
import json
from datetime import datetime, timedelta

from market_lab.canonical_90_four_leg_option_replay_v1 import run


FIELDS = [
    "session_date","instrument_key","strike","side","timestamp",
    "open","high","low","close",
]


def write_csv(path, rows):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def ohlc(inst, side, strike, start, first_low=99, last_close=100):
    rows=[]
    dt=datetime.fromisoformat(start)
    for i in range(1,16):
        t=dt+timedelta(minutes=i)
        rows.append({
            "session_date":"2026-08-25",
            "instrument_key":inst,
            "strike":str(strike),
            "side":side,
            "timestamp":t.isoformat(),
            "open":"100",
            "high":"101",
            "low":str(first_low if i == 1 else 99),
            "close":str(last_close if i == 15 else 100),
        })
    return rows


def test_four_ready_legs_replay_with_common_denominator(tmp_path):
    evidence=tmp_path/"evidence"; evidence.mkdir()
    entry="2026-08-25T09:36:00+05:30"

    legs=[]
    rows=[]
    specs=[
        ("ATM",0,"CE1",24200),
        ("OTM1",1,"CE2",24250),
        ("OTM2",2,"CE3",24300),
        ("OTM3",3,"CE4",24350),
    ]
    for leg,offset,inst,strike in specs:
        legs.append({
            "event_id":"E1",
            "session_date":"2026-08-25",
            "block":"TRAIN",
            "direction":"BULLISH",
            "leg":leg,
            "strike_offset":offset,
            "c1_timestamp":"2026-08-25T09:30:00+05:30",
            "c2_expected_timestamp":"2026-08-25T09:35:00+05:30",
            "option_side":"CE",
            "moving_atm":24200.0,
            "strike":float(strike),
            "instrument_key":inst,
            "entry_timestamp":entry,
            "entry_open":100.0,
            "coverage_status":"READY",
        })
        rows.extend(ohlc(inst,"CE",strike,entry,last_close=103))

    coverage=tmp_path/"coverage.json"
    coverage.write_text(json.dumps({
        "signal_count":1,
        "expected_leg_count":4,
        "legs":legs,
    }))
    write_csv(evidence/"option-ohlc-train.csv",rows)

    r=run(
        coverage_path=coverage,
        evidence_root=evidence,
        output_json=tmp_path/"out.json",
        output_csv=tmp_path/"out.csv",
    )

    assert r["replayed_leg_count"] == 4
    assert r["complete_four_leg_signal_count"] == 1
    assert r["common_complete_signal_comparison"]["signal_count"] == 1
    for leg in ("ATM","OTM1","OTM2","OTM3"):
        assert r["by_leg"][leg]["available_count"] == 1
        assert abs(r["by_leg"][leg]["mean_net_pct"] - 2.5) < 1e-9


def test_frozen_stop_engine_applies_independently_per_leg(tmp_path):
    evidence=tmp_path/"evidence"; evidence.mkdir()
    entry="2026-08-25T09:36:00+05:30"

    legs=[]
    rows=[]
    for leg,offset,inst,strike in [
        ("ATM",0,"CE1",24200),
        ("OTM1",1,"CE2",24250),
        ("OTM2",2,"CE3",24300),
        ("OTM3",3,"CE4",24350),
    ]:
        legs.append({
            "event_id":"E1",
            "session_date":"2026-08-25",
            "block":"TRAIN",
            "direction":"BULLISH",
            "leg":leg,
            "strike_offset":offset,
            "c1_timestamp":"2026-08-25T09:30:00+05:30",
            "c2_expected_timestamp":"2026-08-25T09:35:00+05:30",
            "option_side":"CE",
            "moving_atm":24200.0,
            "strike":float(strike),
            "instrument_key":inst,
            "entry_timestamp":entry,
            "entry_open":100.0,
            "coverage_status":"READY",
        })
        low = 95 if leg == "OTM2" else 99
        rows.extend(ohlc(inst,"CE",strike,entry,first_low=low,last_close=100))

    coverage=tmp_path/"coverage.json"
    coverage.write_text(json.dumps({
        "signal_count":1,
        "expected_leg_count":4,
        "legs":legs,
    }))
    write_csv(evidence/"option-ohlc-train.csv",rows)

    r=run(
        coverage_path=coverage,
        evidence_root=evidence,
        output_json=tmp_path/"out.json",
        output_csv=tmp_path/"out.csv",
    )

    t={x["leg"]:x for x in r["trades"]}
    assert t["OTM2"]["exit_reason"] == "STOP_TOUCH"
    assert abs(t["OTM2"]["net_return_pct"] - (-5.5)) < 1e-9
    assert t["ATM"]["exit_reason"] == "TIME_EXIT"
