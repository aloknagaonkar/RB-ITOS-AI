from market_lab.hilega_milega_audit_report_v1 import build_detailed_audit_report


def test_canonical_audit_report_contains_strategy_reasons_option_lifecycle_and_integrity():
    cp="2026-09-23T10:15:00+05:30"
    rows=[
        {"sequence":1,"checkpoint":cp,"stage":"STRATEGY_DECISION","status":"EVALUATED","payload":{"strategy_id":"HILEGA","strategy_version":"1","state_before":"PATH1_IDLE","bar_open":100,"bar_high":103,"bar_low":99,"bar_close":102,"rsi9":61,"ema3_rsi":55,"wma21_rsi":52,"previous_rsi9":48,"previous_ema3_rsi":50,"previous_wma21_rsi":51,"rsi_cross_ema_up":True,"rsi_gt_50":True,"rsi_gt_wma":True,"ema_gt_wma":True,"rsi_rising":True,"ema_rising":True,"full_alignment":True},"previous_hash":None,"record_hash":"a"},
        {"sequence":2,"checkpoint":cp,"stage":"STRATEGY_TRANSITION","status":"ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21","payload":{"event_type":"ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21","event_time":cp,"price":102,"source":"PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21","state_before":"PATH1_IDLE","state_after":"BULLISH_ACTIVE"},"previous_hash":"a","record_hash":"b"},
        {"sequence":3,"checkpoint":cp,"stage":"STRATEGY_DECISION_RESULT","status":"COMPLETE","payload":{"state_after":"BULLISH_ACTIVE","selected_route":"ROUTE_A","route_b_suppressed_by_route_a_priority":True,"events_emitted":["ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21"],"route_a_eligible":True,"route_a_pass":True,"route_a_fail_reasons":[],"route_b_eligible":True,"route_b_pass":True,"route_b_fail_reasons":[]},"previous_hash":"b","record_hash":"c"},
        {"sequence":4,"checkpoint":None,"stage":"OPTION_CANDIDATE_SET","status":"PASS","payload":{"signal_bar":cp,"expiry":"2026-09-29","atm":23400,"candidates":[{"strike":23400}]},"previous_hash":"c","record_hash":"d"},
        {"sequence":5,"checkpoint":None,"stage":"OPTION_SHADOW_LIFECYCLE_START","status":"PASS","payload":{"signal_bar":cp,"active":True,"legs":[{"strike":23400}]},"previous_hash":"d","record_hash":"e"},
    ]
    report=build_detailed_audit_report(rows,checkpoint=cp,mode="LIVE_SHADOW",chain_ok=True)
    assert report["strategy"]["selected_route"]=="ROUTE_A"
    assert report["route_a"]["pass"] is True
    assert report["strategy"]["route_b_suppressed_by_route_a_priority"] is True
    assert report["option_candidate"]["expiry"]=="2026-09-29"
    assert report["option_lifecycle"]["start"]["active"] is True
    assert report["audit_integrity"]["chain_ok"] is True
    assert report["safety"]["execution_enabled"] is False
