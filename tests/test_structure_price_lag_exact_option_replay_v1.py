import csv, json
from pathlib import Path
from market_lab.structure_price_lag_exact_option_replay_v1 import (
    build_replay, build_report
)

def test_exact_atm_next_minute_and_50pt_bridge(tmp_path: Path):
    events = tmp_path/"events.csv"
    fields = [
        "event_id","session_date","direction","price_lag_class",
        "confirmation_timestamp_candle2","confirmation_spot_c2",
        "hit_20pt","time_to_20pt_minutes","timestamp_hit_20pt",
        "hit_30pt","time_to_30pt_minutes","timestamp_hit_30pt",
        "hit_40pt","time_to_40pt_minutes","timestamp_hit_40pt",
        "hit_50pt","time_to_50pt_minutes","timestamp_hit_50pt",
        "hit_75pt","time_to_75pt_minutes","timestamp_hit_75pt",
        "hit_100pt","time_to_100pt_minutes","timestamp_hit_100pt",
    ]
    row = {k:"" for k in fields}
    row.update({
        "event_id":"1","session_date":"2026-01-01","direction":"BULLISH",
        "price_lag_class":"SPOT_LAG",
        "confirmation_timestamp_candle2":"2026-01-01T10:00:00+05:30",
        "confirmation_spot_c2":"24000",
        "hit_50pt":"true","time_to_50pt_minutes":"10",
        "timestamp_hit_50pt":"2026-01-01T10:10:00+05:30"
    })
    with events.open("w", newline="") as f:
        w=csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerow(row)

    pos = [{
        "session_date":"2026-01-01","timestamp":"2026-01-01T10:00:00+05:30",
        "moving_atm":"24000","strike":"24000","strike_offset":"0",
        "ce_instrument_key":"CE24000","pe_instrument_key":"PE24000"
    }]
    ohlc = []
    base = [
        ("2026-01-01T10:01:00+05:30",100,101,99,100),
        ("2026-01-01T10:02:00+05:30",101,104,100,103),
        ("2026-01-01T10:04:00+05:30",105,107,104,106),
        ("2026-01-01T10:06:00+05:30",106,110,105,109),
        ("2026-01-01T10:10:00+05:30",120,127,118,125),
        ("2026-01-01T10:11:00+05:30",126,130,125,128),
        ("2026-01-01T10:16:00+05:30",130,140,129,138),
        ("2026-01-01T10:31:00+05:30",145,150,140,148),
        ("2026-01-01T11:01:00+05:30",155,160,150,158),
    ]
    for ts,o,h,l,c in base:
        ohlc.append({"instrument_key":"CE24000","timestamp":ts,"open":o,"high":h,"low":l,"close":c})

    date_map={"2026-01-01":"OOS_E"}
    trades, issues, n = build_replay(events,date_map,{"OOS_E":pos},{"OOS_E":ohlc})
    assert n == 1 and not issues and len(trades)==1
    t=trades[0]
    assert t["entry_open"] == 100
    assert t["option_side"] == "CE"
    assert t["strike"] == 24000
    assert t["option_points_at_nifty_50pt"] == 25
    assert t["option_gross_pct_at_nifty_50pt"] == 25

def test_missing_exact_next_minute_is_not_filled(tmp_path: Path):
    events = tmp_path/"events.csv"
    with events.open("w", newline="") as f:
        fields=["event_id","session_date","direction","price_lag_class",
                "confirmation_timestamp_candle2","confirmation_spot_c2"]
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerow({
            "event_id":"1","session_date":"2026-01-01","direction":"BEARISH",
            "price_lag_class":"SPOT_LAG",
            "confirmation_timestamp_candle2":"2026-01-01T10:00:00+05:30",
            "confirmation_spot_c2":"24000"
        })
    pos=[{"session_date":"2026-01-01","timestamp":"2026-01-01T10:00:00+05:30",
          "moving_atm":"24000","strike":"24000","strike_offset":"0",
          "pe_instrument_key":"PE24000"}]
    trades, issues, _ = build_replay(events,{"2026-01-01":"OOS_E"},{"OOS_E":pos},{"OOS_E":[]})
    assert trades == []
    assert issues["NO_EXACT_NEXT_MINUTE_OPEN"] == 1
