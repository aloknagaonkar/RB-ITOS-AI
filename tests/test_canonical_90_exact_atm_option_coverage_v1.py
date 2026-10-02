import csv
import json
from pathlib import Path

from market_lab.canonical_90_exact_atm_option_coverage_v1 import run


def write_csv(path, fields, rows):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def test_exact_atm_next_minute_full_path(tmp_path):
    decisions = tmp_path / "decisions"
    evidence = tmp_path / "evidence"
    decisions.mkdir()
    evidence.mkdir()

    event = {
        "event_id": "2026-08-25-0930-BULLISH",
        "session_date": "2026-08-25",
        "direction": "BULLISH",
        "c1_timestamp": "2026-08-25T09:30:00+05:30",
        "c2_expected_timestamp": "2026-08-25T09:35:00+05:30",
        "final_decision": "TRADE_ELIGIBLE",
    }
    (decisions / "2026-08-25.json").write_text(
        json.dumps({"events": [event]})
    )

    pos_fields = [
        "session_date","timestamp","moving_atm","strike","strike_offset",
        "ce_instrument_key","pe_instrument_key",
    ]
    write_csv(
        evidence / "positioning-train.csv",
        pos_fields,
        [{
            "session_date":"2026-08-25",
            "timestamp":"2026-08-25T09:35:00+05:30",
            "moving_atm":"24200",
            "strike":"24200",
            "strike_offset":"0",
            "ce_instrument_key":"CE1",
            "pe_instrument_key":"PE1",
        }],
    )

    ohlc_fields = [
        "session_date","instrument_key","strike","side","timestamp",
        "open","high","low","close",
    ]
    rows = []
    for i in range(16):
        minute = 36 + i
        hh = 9 + minute // 60
        mm = minute % 60
        rows.append({
            "session_date":"2026-08-25",
            "instrument_key":"CE1",
            "strike":"24200",
            "side":"CE",
            "timestamp":f"2026-08-25T{hh:02d}:{mm:02d}:00+05:30",
            "open":"100","high":"105","low":"95","close":"102",
        })
    write_csv(evidence / "option-ohlc-train.csv", ohlc_fields, rows)

    out = tmp_path / "out.json"
    result = run(
        decision_root=decisions,
        evidence_root=evidence,
        output=out,
    )

    assert result["candidate_count"] == 1
    assert result["ready_count"] == 1
    row = result["rows"][0]
    assert row["coverage_status"] == "READY"
    assert row["option_side"] == "CE"
    assert row["strike"] == 24200.0
    assert row["entry_timestamp"] == "2026-08-25T09:36:00+05:30"
    assert row["path_rows_available"] == 16


def test_missing_entry_minute_fails_closed(tmp_path):
    decisions = tmp_path / "decisions"
    evidence = tmp_path / "evidence"
    decisions.mkdir()
    evidence.mkdir()

    event = {
        "event_id": "2026-08-25-0930-BEARISH",
        "session_date": "2026-08-25",
        "direction": "BEARISH",
        "c1_timestamp": "2026-08-25T09:30:00+05:30",
        "c2_expected_timestamp": "2026-08-25T09:35:00+05:30",
        "final_decision": "TRADE_ELIGIBLE",
    }
    (decisions / "2026-08-25.json").write_text(
        json.dumps({"events": [event]})
    )

    pos_fields = [
        "session_date","timestamp","moving_atm","strike","strike_offset",
        "ce_instrument_key","pe_instrument_key",
    ]
    write_csv(
        evidence / "positioning-train.csv",
        pos_fields,
        [{
            "session_date":"2026-08-25",
            "timestamp":"2026-08-25T09:35:00+05:30",
            "moving_atm":"24200",
            "strike":"24200",
            "strike_offset":"0",
            "ce_instrument_key":"CE1",
            "pe_instrument_key":"PE1",
        }],
    )

    ohlc_fields = [
        "session_date","instrument_key","strike","side","timestamp",
        "open","high","low","close",
    ]
    rows = [{
        "session_date":"2026-08-25",
        "instrument_key":"PE1",
        "strike":"24200",
        "side":"PE",
        "timestamp":"2026-08-25T09:37:00+05:30",
        "open":"100","high":"105","low":"95","close":"102",
    }]
    write_csv(evidence / "option-ohlc-train.csv", ohlc_fields, rows)

    result = run(
        decision_root=decisions,
        evidence_root=evidence,
        output=tmp_path/"out.json",
    )
    assert result["rows"][0]["coverage_status"] == "MISSING_ENTRY_MINUTE"
