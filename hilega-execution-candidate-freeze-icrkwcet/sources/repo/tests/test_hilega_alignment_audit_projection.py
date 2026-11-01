import market_lab.hilega_directional_candle_ui_v1 as m

def test_alignment_audit_exposes_recorded_indicators_without_synthetic_previous(monkeypatch):
    day='2026-10-12'
    monkeypatch.setattr(m,'_directional_evidence_live_rows',lambda *a,**kw:{})
    monkeypatch.setattr(m,'_base_live_rows_legacy',lambda *a:{})
    monkeypatch.setattr(m,'_read_audit',lambda *a:[{'stage':'DIRECTIONAL_DECISION','status':'PROCESSED','payload':{
        'strategy_id':'HILEGA_V2_ALIGNMENT_DUAL_EXIT','decision_timestamp':day+'T09:43:00+05:30',
        'bar_timestamp':day+'T09:35:00+05:30','nifty_close':22521.35,
        'trade_owner_before':'BEARISH','trade_owner_after':'BEARISH',
        'completed_5m_indicators':{'rsi9':30,'ema3':32,'wma21':40},
        'exit_validation':{'dual_exit_pass':False},'minute_ohlcv':{'open':22520,'high':22525,'low':22519,'volume':0}}}])
    row=m.build_live_directional_candles(day,audit_only=True)['rows'][0]
    assert (row['rsi9'],row['ema3_rsi'],row['wma21_rsi'])==(30,32,40)
    assert row['exit_validation']['dual_exit_pass'] is False
    assert row['open']==22520 and row['volume']==0
    assert row.get('previous_rsi9') is None
