from market_lab import hilega_directional_candle_ui_v1 as candles
from market_lab.hilega_historical_ui_api_v1 import _directional_report

def test_minute_events_survive_recovery(monkeypatch):
    day="2026-10-09"
    def record(at, events, status="PROCESSED", price=100):
        return {"stage":"DIRECTIONAL_DECISION", "status":status, "payload":{
            "strategy_id":"HILEGA_WMA_GAP_V2_LIVE_SHADOW",
            "bar_timestamp":day+"T10:05:00+05:30", "decision_timestamp":day+"T"+at+":00+05:30",
            "accepted_events":events, "nifty_close":price,
            "event_details":[{"event_type":e,"price":price,"entry_price":100,
                              "entry_time":day+"T10:12:00+05:30","points":-11.25} for e in events]}}
    records=[record("10:12",["ENTRY_BEARISH_ROUTE_A"],price=100),
             record("10:13",[]),record("10:12",[],"RECOVERED"),
             record("10:14",["STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21"],price=111.25)]
    monkeypatch.setattr(candles,"_base_live_rows",lambda day:{})
    monkeypatch.setattr(candles,"_read_audit",lambda path:records)
    rows=candles.build_live_directional_candles(day)["rows"]
    assert len(rows)==3
    assert rows[0]["accepted_events"]=="ENTRY_BEARISH_ROUTE_A"
    report=_directional_report(rows[-1]);event=report["transitions"][0]
    assert report["checkpoint"].endswith("10:14:00+05:30")
    assert event["price"]==111.25 and event["entry_price"]==100
    assert event["points"]==-11.25
    assert event["details"]["original_entry_time"].endswith("10:12:00+05:30")
