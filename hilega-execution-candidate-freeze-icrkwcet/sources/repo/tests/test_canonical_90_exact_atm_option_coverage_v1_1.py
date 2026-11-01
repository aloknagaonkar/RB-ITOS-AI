import csv
import json
from datetime import datetime, timedelta

from market_lab.canonical_90_exact_atm_option_coverage_v1 import run


def write_csv(path, fields, rows):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _event(event_id, c1, c2, direction="BULLISH"):
    return {
        "event_id": event_id,
        "session_date": "2026-08-25",
        "direction": direction,
        "c1_timestamp": c1,
        "c2_expected_timestamp": c2,
        "final_decision": "TRADE_ELIGIBLE",
    }


def _positioning_row(ts, ce="CE1", pe="PE1"):
    return {
        "session_date":"2026-08-25",
        "timestamp":ts,
        "moving_atm":"24200",
        "strike":"24200",
        "strike_offset":"0",
        "ce_instrument_key":ce,
        "pe_instrument_key":pe,
    }


def _ohlc_row(ts, instrument="CE1", side="CE"):
    return {
        "session_date":"2026-08-25",
        "instrument_key":instrument,
        "strike":"24200",
        "side":side,
        "timestamp":ts,
        "open":"100","high":"105","low":"95","close":"102",
    }


def test_multiple_events_same_contract_each_get_own_window(tmp_path):
    decisions=tmp_path/"decisions"; evidence=tmp_path/"evidence"
    decisions.mkdir(); evidence.mkdir()

    events=[
        _event("E1","2026-08-25T09:30:00+05:30","2026-08-25T09:35:00+05:30"),
        _event("E2","2026-08-25T10:00:00+05:30","2026-08-25T10:05:00+05:30"),
    ]
    (decisions/"2026-08-25.json").write_text(json.dumps({"events":events}))

    pos_fields=["session_date","timestamp","moving_atm","strike","strike_offset","ce_instrument_key","pe_instrument_key"]
    write_csv(evidence/"positioning-train.csv",pos_fields,[
        _positioning_row("2026-08-25T09:35:00+05:30"),
        _positioning_row("2026-08-25T10:05:00+05:30"),
    ])

    ohlc_fields=["session_date","instrument_key","strike","side","timestamp","open","high","low","close"]
    rows=[]
    for start in ("2026-08-25T09:36:00+05:30","2026-08-25T10:06:00+05:30"):
        dt=datetime.fromisoformat(start)
        for i in range(16):
            rows.append(_ohlc_row((dt+timedelta(minutes=i)).isoformat()))
    write_csv(evidence/"option-ohlc-train.csv",ohlc_fields,rows)

    r=run(decision_root=decisions,evidence_root=evidence,output=tmp_path/"out.json")
    assert r["candidate_count"]==2
    assert r["coverage_counts"]=={"READY":2}


def test_late_entry_is_session_end_censored(tmp_path):
    decisions=tmp_path/"decisions"; evidence=tmp_path/"evidence"
    decisions.mkdir(); evidence.mkdir()

    event=_event(
        "E-LATE",
        "2026-08-25T15:15:00+05:30",
        "2026-08-25T15:20:00+05:30",
    )
    (decisions/"2026-08-25.json").write_text(json.dumps({"events":[event]}))

    pos_fields=["session_date","timestamp","moving_atm","strike","strike_offset","ce_instrument_key","pe_instrument_key"]
    write_csv(
        evidence/"positioning-train.csv",
        pos_fields,
        [_positioning_row("2026-08-25T15:20:00+05:30")],
    )

    ohlc_fields=["session_date","instrument_key","strike","side","timestamp","open","high","low","close"]
    rows=[_ohlc_row(f"2026-08-25T15:{m:02d}:00+05:30") for m in range(21,30)]
    write_csv(evidence/"option-ohlc-train.csv",ohlc_fields,rows)

    r=run(decision_root=decisions,evidence_root=evidence,output=tmp_path/"out.json")
    row=r["rows"][0]
    assert row["coverage_status"]=="SESSION_END_CENSORED"
    assert row["path_rows_available"]==9
    assert row["missing_timestamps"][0]=="2026-08-25T15:30:00+05:30"
