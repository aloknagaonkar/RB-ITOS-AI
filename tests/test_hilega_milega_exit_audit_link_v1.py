from market_lab.hilega_milega_audit_report_v1 import build_detailed_audit_report


def test_exit_audit_links_original_entry_all_ce_prices():
    entry='2026-09-23T10:15:00+05:30'; exit_cp='2026-09-23T10:35:00+05:30'
    def row(cp, stage, payload, status='PASS'):
        return {'checkpoint':cp,'stage':stage,'payload':payload,'status':status}
    rows=[row(entry,'STRATEGY_DECISION',{'rsi9':55}),
          row(exit_cp,'STRATEGY_DECISION',{'rsi9':40}),
          row(exit_cp,'STRATEGY_TRANSITION',{'event_type':'STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21','details':{'original_entry_time':entry}}),
          row('2026-09-23T10:20:10+05:30','OPTION_SHADOW_LIFECYCLE_START',{'signal_bar':entry,'legs':[{'entry_open':120,'relation_to_atm':0}]},'PASS'),
          row('2026-09-23T10:40:10+05:30','OPTION_SHADOW_LIFECYCLE_EXIT',{'signal_bar':entry,'legs':[{'entry_open':120,'exit_open':132,'realized_points':12,'relation_to_atm':0}]},'PASS')]
    report=build_detailed_audit_report(rows,checkpoint=exit_cp,mode='LIVE_SHADOW',chain_ok=True)
    assert report['linked_signal_bar']==entry
    assert report['option_lifecycle']['start']['legs'][0]['entry_open']==120
    assert report['option_lifecycle']['exit']['legs'][0]['exit_open']==132
    assert report['transitions'][0]['event_type']=='STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'
