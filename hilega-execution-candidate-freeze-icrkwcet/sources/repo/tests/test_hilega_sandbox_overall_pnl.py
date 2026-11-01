from types import SimpleNamespace
import market_lab.hilega_upstox_sandbox_basket_v2 as m

def test_all_sessions_survive_new_arm_and_worker_reload(tmp_path,monkeypatch):
    control=tmp_path/'control';journal=tmp_path/'journal'
    w=m.BasketWorker(control=control,journal=journal)
    for day,exit_price in [('2026-10-08',110),('2026-10-09',95)]:
        for role in range(-2,3):
            contract=dict(role=role,instrument_key=f'K{role}',strike=22000+role*50,expiry='2026-10-13',option_type='CE',lot_size=65)
            for event,price in [('ENTRY',100),('EXIT',exit_price)]:
                w.store.append(dict(status='ACCEPTED',session_date=day,trade_id=day,role=role,event_type=event,contract=contract,quantity=65,observed_option_price=price,broker_order_id=f'{day}-{role}-{event}',timestamp=day+'T10:00:00+05:30',event_timestamp=day+'T10:00:00+05:30',direction='BULLISH',strategy_id='S',request_id=f'{day}-{role}-{event}'))
    w.control.write(dict(session_date='2026-10-09'))
    real=m.BasketWorker
    monkeypatch.setattr(m,'BasketWorker',lambda **kw:real(control=control,journal=journal))
    monkeypatch.setattr(m.SandboxConfig,'from_env',lambda _:SimpleNamespace(lots=1,analytics_token='',sandbox_token=''))
    result=m.build_dashboard()
    assert result['pnl']['closed_estimated_rupees']==-1625
    assert result['overall_pnl']['gross_profit_rupees']==3250
    assert result['overall_pnl']['gross_loss_rupees']==1625
    assert result['overall_pnl']['total_estimated_rupees']==1625
    assert result['overall_pnl']['completed_baskets']==2
    assert len(result['completed_trades'])==2
    w.control.write(dict(session_date='2026-10-12'))
    again=m.build_dashboard()
    assert again['pnl']['total_estimated_rupees']==0
    assert again['overall_pnl']==result['overall_pnl']
    assert again['worker']['accepted_orders_this_session']==0
    assert len(again['completed_trades'])==2
