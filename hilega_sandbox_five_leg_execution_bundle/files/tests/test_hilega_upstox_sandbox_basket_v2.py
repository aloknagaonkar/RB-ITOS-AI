from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import pytest
from market_lab.hilega_upstox_sandbox_basket_v2 import BasketWorker,select_five,ensure_clear
NOW=datetime.fromisoformat('2026-10-08T12:30:00+05:30')
class Fake:
    def __init__(self,fail=None):self.calls=[];self.fail=fail;self.resolves=0
    def resolve_five(self,direction,day):
        self.resolves+=1
        return [dict(role=i,expiry='2026-10-13',strike=22350+i*50,option_type='CE' if direction=='BULLISH' else 'PE',instrument_key=f'K{i}',lot_size=65) for i in range(-2,3)]
    def instrument_ltp(self,key):return 100
    def place_market(self,**kw):
        self.calls.append(kw)
        if len(self.calls)==self.fail:raise TimeoutError()
        return 'order-'+str(len(self.calls))
def fixture(tmp_path):
    w=BasketWorker(control=tmp_path/'control.json',journal=tmp_path/'events.jsonl',clock=lambda:NOW)
    w.control.write(dict(armed=True,kill_switch=False,session_date='2026-10-08',baseline_source_sequence=10,strategy_id='HILEGA_DIRECTIONAL_SHADOW_V1'))
    return w,SimpleNamespace(lots=1)
def intent(kind,trade='t',seq=11):return dict(intent_id=f'{trade}-{kind}',event_id=f'{trade}-{kind}',trade_id=trade,event_type=kind,direction='BEARISH',event_timestamp=NOW.isoformat(),source_sequence=seq,decision='WOULD_SUBMIT')
def test_five_buys_same_contract_exits_and_idempotent(tmp_path):
    w,c=fixture(tmp_path);f=Fake();en=intent('ENTRY');ex=intent('EXIT',seq=12)
    w.process(en,[en,ex],f,c);w.process(en,[en,ex],f,c)
    assert len(f.calls)==5 and len(w.store.open_legs())==5
    w.process(ex,[en,ex],f,c);w.process(ex,[en,ex],f,c)
    assert len(f.calls)==10 and w.store.open_legs()==[] and f.resolves==1
    assert [r['transaction_type'] for r in f.calls]==['BUY']*5+['SELL']*5
    assert [(r['instrument_key'],r['quantity']) for r in f.calls[:5]]==[(r['instrument_key'],r['quantity']) for r in f.calls[5:]]
def test_no_daily_order_count_cap(tmp_path):
    w,c=fixture(tmp_path);f=Fake()
    for i in range(3):
        en=intent('ENTRY',str(i),11+2*i);ex=intent('EXIT',str(i),12+2*i)
        w.process(en,[en,ex],f,c);w.process(ex,[en,ex],f,c)
    assert len(f.calls)==30 and len(w.store.accepted())==30

def test_partial_entry_unknown_not_retried_known_legs_exit(tmp_path):
    w,c=fixture(tmp_path);f=Fake(fail=3);en=intent('ENTRY');ex=intent('EXIT',seq=12)
    w.process(en,[en,ex],f,c)
    assert len(f.calls)==3 and len(w.store.open_legs())==2 and len(w.store.uncertain())==1
    w.process(en,[en,ex],f,c);assert len(f.calls)==3
    w.process(ex,[en,ex],f,c)
    assert len(f.calls)==5 and not w.store.open_legs()
    assert w.control.read()['entries_blocked'] is True
    with pytest.raises(ValueError):ensure_clear(w.store)

def test_partial_exit_continues_other_legs_without_duplicate(tmp_path):
    w,c=fixture(tmp_path);f=Fake(fail=7);en=intent('ENTRY');ex=intent('EXIT',seq=12)
    w.process(en,[en,ex],f,c);w.process(ex,[en,ex],f,c)
    assert len(f.calls)==10 and len(w.store.open_legs())==1
    w.process(ex,[en,ex],f,c);assert len(f.calls)==10

def test_prearm_exit_and_overlap_guard(tmp_path):
    w,c=fixture(tmp_path);f=Fake();en=intent('ENTRY',seq=9);ex=intent('EXIT')
    w.process(ex,[en,ex],f,c);assert not f.calls
    fresh=intent('ENTRY','fresh');w.process(fresh,[fresh],f,c)
    other=intent('ENTRY','other',12);w.process(other,[other],f,c)
    assert len(f.calls)==5 and w.store.rows()[-1]['status']=='ENTRY_BLOCKED'

def test_nearest_expiry_five_strikes_and_missing_guard():
    rows=[dict(expiry=expiry,instrument_type=side,strike_price=22000+i*50,instrument_key=f'{expiry}-{side}-{i}',lot_size=65) for expiry in ('2026-10-06','2026-10-13','2026-10-20') for side in ('CE','PE') for i in range(10)]
    selected=select_five(rows,22260,'BEARISH','2026-10-08')
    assert [r['strike'] for r in selected]==[22150,22200,22250,22300,22350]
    assert all(r['expiry']=='2026-10-13' and r['option_type']=='PE' for r in selected)
    with pytest.raises(ValueError):select_five(rows,22000,'BEARISH','2026-10-08')

def test_dashboard_five_legs_missing_prices_and_no_duplicate_pnl(tmp_path,monkeypatch):
    import market_lab.hilega_upstox_sandbox_basket_v2 as m
    w,c=fixture(tmp_path);f=Fake();en=intent('ENTRY');ex=intent('EXIT',seq=12)
    w.process(en,[en,ex],f,c)
    real=m.BasketWorker
    monkeypatch.setattr(m,'BasketWorker',lambda **kw:w)
    monkeypatch.setattr(m.SandboxConfig,'from_env',lambda _:SimpleNamespace(lots=1,analytics_token='a',sandbox_token='s'))
    class Quotes:
        def __init__(self,*args):pass
        def quotes(self,keys):return {k:110 for k in keys[:4]}
        def close(self):pass
    monkeypatch.setattr(m,'BasketTransport',Quotes)
    result=m.build_dashboard()
    assert len(result['active_trades'])==1 and len(result['active_trades'][0]['legs'])==5
    assert result['pnl']['missing_pnl_legs']==1 and result['pnl']['open_estimated_rupees']==2600
    w.process(ex,[en,ex],f,c)
    result=m.build_dashboard()
    assert not result['active_trades'] and len(result['completed_trades'])==1
    assert result['pnl']['closed_estimated_rupees']==0 and result['worker']['accepted_orders_this_session']==10

def test_partial_basket_dashboard_shows_unknown_and_unsubmitted(tmp_path,monkeypatch):
    import market_lab.hilega_upstox_sandbox_basket_v2 as m
    w,c=fixture(tmp_path);f=Fake(fail=3);en=intent('ENTRY');w.process(en,[en],f,c)
    monkeypatch.setattr(m,'BasketWorker',lambda **kw:w)
    monkeypatch.setattr(m.SandboxConfig,'from_env',lambda _:SimpleNamespace(lots=1,analytics_token='',sandbox_token=''))
    result=m.build_dashboard();legs=result['active_trades'][0]['legs']
    assert len(legs)==5
    assert [l['status'] for l in legs]==['BUY_ACKNOWLEDGED','BUY_ACKNOWLEDGED','SUBMISSION_UNCERTAIN','NOT_SUBMITTED','NOT_SUBMITTED']
    assert result['active_trades'][0]['status']=='RECONCILIATION_REQUIRED'
