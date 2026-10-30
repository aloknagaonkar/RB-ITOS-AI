import csv
import json
from pathlib import Path

from market_lab.canonical_90_exact_atm_option_replay_v1 import run


def write_csv(path, fields, rows):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def base_coverage(tmp_path, event):
    p = tmp_path / "coverage.json"
    p.write_text(json.dumps({
        "rows": [event],
        "coverage_counts": {"READY": 1},
    }))
    return p


def event(entry_open=100.0):
    return {
        "event_id":"E1",
        "session_date":"2026-08-25",
        "block":"TRAIN",
        "direction":"BULLISH",
        "c1_timestamp":"2026-08-25T09:30:00+05:30",
        "c2_expected_timestamp":"2026-08-25T09:35:00+05:30",
        "futures_state":"SHORT_COVERING",
        "option_side":"CE",
        "strike":24200.0,
        "moving_atm":24200.0,
        "instrument_key":"CE1",
        "entry_timestamp":"2026-08-25T09:36:00+05:30",
        "entry_open":entry_open,
        "coverage_status":"READY",
    }


FIELDS = [
    "session_date","instrument_key","strike","side","timestamp",
    "open","high","low","close",
]


def row(ts, o, h, l, c):
    return {
        "session_date":"2026-08-25",
        "instrument_key":"CE1",
        "strike":"24200",
        "side":"CE",
        "timestamp":ts,
        "open":str(o),"high":str(h),"low":str(l),"close":str(c),
    }


def test_stop_touch_and_cost_match_existing_engine(tmp_path):
    evidence = tmp_path / "evidence"; evidence.mkdir()
    coverage = base_coverage(tmp_path, event())

    rows = []
    # entry+1 hits the frozen -5% stop exactly by LOW.
    rows.append(row("2026-08-25T09:37:00+05:30", 100, 101, 95, 96))
    # remaining rows are present though replay exits immediately.
    for minute in range(38, 52):
        rows.append(row(f"2026-08-25T09:{minute:02d}:00+05:30", 100, 101, 99, 100))
    write_csv(evidence/"option-ohlc-train.csv", FIELDS, rows)

    r = run(
        coverage_path=coverage,
        evidence_root=evidence,
        output_json=tmp_path/"out.json",
        output_csv=tmp_path/"out.csv",
    )
    t = r["trades"][0]
    assert t["exit_reason"] == "STOP_TOUCH"
    assert abs(t["gross_return_pct"] - (-5.0)) < 1e-9
    assert abs(t["net_return_pct"] - (-5.5)) < 1e-9


def test_be_and_trail_activate_next_bar(tmp_path):
    evidence = tmp_path / "evidence"; evidence.mkdir()
    coverage = base_coverage(tmp_path, event())

    rows = [
        # +10% high arms BE and trail, but new stop is not active in this bar.
        row("2026-08-25T09:37:00+05:30", 100, 110, 96, 109),
        # Next bar opens below the newly active trailing stop (106.7),
        # so exit must be at bar OPEN.
        row("2026-08-25T09:38:00+05:30", 105, 106, 104, 105),
    ]
    for minute in range(39, 52):
        rows.append(row(f"2026-08-25T09:{minute:02d}:00+05:30", 105, 106, 104, 105))
    write_csv(evidence/"option-ohlc-train.csv", FIELDS, rows)

    r = run(
        coverage_path=coverage,
        evidence_root=evidence,
        output_json=tmp_path/"out.json",
        output_csv=tmp_path/"out.csv",
    )
    t = r["trades"][0]
    assert t["be_armed"] is True
    assert t["trail_armed"] is True
    assert t["exit_reason"] == "STOP_GAP"
    assert t["exit_price"] == 105.0


def test_exact_plus15_time_exit(tmp_path):
    evidence = tmp_path / "evidence"; evidence.mkdir()
    coverage = base_coverage(tmp_path, event())

    rows = []
    for minute in range(37, 52):  # exactly +1 through +15
        close = 103 if minute == 51 else 100
        rows.append(row(f"2026-08-25T09:{minute:02d}:00+05:30", 100, 101, 99, close))
    write_csv(evidence/"option-ohlc-train.csv", FIELDS, rows)

    r = run(
        coverage_path=coverage,
        evidence_root=evidence,
        output_json=tmp_path/"out.json",
        output_csv=tmp_path/"out.csv",
    )
    t = r["trades"][0]
    assert t["exit_reason"] == "TIME_EXIT"
    assert t["exit_timestamp"] == "2026-08-25T09:51:00+05:30"
    assert abs(t["gross_return_pct"] - 3.0) < 1e-9
    assert abs(t["net_return_pct"] - 2.5) < 1e-9
