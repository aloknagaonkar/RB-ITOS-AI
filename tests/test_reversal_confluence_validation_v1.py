import csv
import json
from pathlib import Path

from market_lab.reversal_confluence_validation_v1 import (
    build_report,
    build_transition_events,
    load_audits,
    load_state_rows,
)

def test_reversal_confluence(tmp_path: Path):
    rows = tmp_path / "rows.csv"
    fields = ["session_date","timestamp","horizon","existing_horizon_state"]
    data = []
    def add(ts, state):
        for h in ("5m","10m","15m"):
            data.append({
                "session_date":"2026-01-01",
                "timestamp":ts,
                "horizon":h,
                "existing_horizon_state":state,
            })
    add("2026-01-01T09:30:00+05:30","BEARISH")
    add("2026-01-01T09:35:00+05:30","BEARISH")
    add("2026-01-01T09:40:00+05:30","MIXED")
    add("2026-01-01T09:45:00+05:30","BULLISH")
    add("2026-01-01T09:50:00+05:30","BULLISH")
    add("2026-01-01T09:55:00+05:30","BULLISH")
    with rows.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(data)

    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({
        "session_date":"2026-01-01",
        "rows":[{
            "timestamp":"2026-01-01T09:45:00+05:30",
            "session_imbalance":100,
            "session_pcr_change_0920_to_now":0.2,
            "futures_oi_direction":"BULLISH",
            "futures_oi_status":"LONG_BUILDUP",
            "bullish_oi_status_streak":2,
            "vwap_side":"ABOVE",
            "strategy_p1":"BULLISH",
            "strategy_p2_confirmed":None,
        }]
    }))

    events = build_transition_events(load_state_rows(rows), load_audits([audit]))
    assert len(events) == 1
    e = events[0]
    assert e["to_state"] == "BULLISH_ALL_3"
    assert e["gap_candles"] == 1
    assert e["resulting_run_length"] == 3
    assert e["resulting_run_bucket"] == "THREE_PLUS"
    assert e["supportive_confluence_components"] == 4
    assert e["available_confluence_components"] == 4

    report = build_report(events)
    assert report["status"] == "PASS"
    assert report["by_resulting_run_bucket"]["THREE_PLUS"]["events"] == 1
