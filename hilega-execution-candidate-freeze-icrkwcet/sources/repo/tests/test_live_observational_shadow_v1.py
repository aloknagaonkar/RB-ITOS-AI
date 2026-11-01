from market_lab.live_observational_shadow_v1 import AuditStore, ShadowEngine, reconstruct_states, daily_summary

def test_full_flow(tmp_path):
    store=AuditStore(tmp_path/'events.jsonl'); e=ShadowEngine(store)
    oid=e.detect('2026-09-18','BULLISH','BULLISH_ALL_3','2026-09-18T10:00:00+05:30',25010,'OBS-1')
    e.confirm_candle2(oid,'2026-09-18T10:05:00+05:30',25005,True)
    e.check_futures(oid,'2026-09-18T10:05:01+05:30','LONG_BUILDUP',True)
    assert e.classify_spot_lag(oid,'2026-09-18T10:05:02+05:30')=='SPOT_LAG'
    e.resolve_option(oid,'2026-09-18T10:05:03+05:30',25000,'CE25000')
    e.open_hypothetical_entry(oid,'2026-09-18T10:06:00+05:30',100)
    e.process_option_bar(oid,'2026-09-18T10:07:00+05:30',100,106,99,105)
    e.process_option_bar(oid,'2026-09-18T10:08:00+05:30',104,105,99,100)
    s=reconstruct_states(store.read_all())[oid]
    assert s.status=='CLOSED' and s.exit_reason=='STOP_TOUCH' and round(s.net_return_pct,6)==-0.5
    assert store.verify_chain()==(True,None)
    r=daily_summary([s],'2026-09-18'); assert r['closed_trade_count']==1 and r['spot_lag_closed_count']==1

def test_rejection_is_audited(tmp_path):
    store=AuditStore(tmp_path/'events.jsonl'); e=ShadowEngine(store)
    oid=e.detect('2026-09-18','BEARISH','BEARISH_ALL_3','2026-09-18T11:00:00+05:30',25000,'OBS-2')
    e.confirm_candle2(oid,'2026-09-18T11:05:00+05:30',25010,False)
    s=reconstruct_states(store.read_all())[oid]; assert s.status=='REJECTED' and s.rejection_reason=='ALL3_DID_NOT_SURVIVE_CANDLE2'

def test_hash_chain_detects_edit(tmp_path):
    p=tmp_path/'events.jsonl'; store=AuditStore(p); e=ShadowEngine(store)
    e.detect('2026-09-18','BULLISH','BULLISH_ALL_3','2026-09-18T12:00:00+05:30',25000,'OBS-3')
    assert store.verify_chain()[0]
    p.write_text(p.read_text().replace('25000.0','25001.0'))
    assert not AuditStore(p).verify_chain()[0]
