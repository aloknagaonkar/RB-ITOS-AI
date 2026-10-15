from datetime import datetime
import hashlib
import json
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
    assert len(f.calls)==5 and w.store.rows()[-1]['status']=='ENTRY_NOT_TRADED'
    assert w.store.rows()[-1]['reason']=='OPEN_BASKET_OR_RECONCILIATION_REQUIRED'
    other_exit=intent('EXIT','other',13)
    w.process(other_exit,[other,other_exit],f,c)
    assert len(f.calls)==5 and w.store.rows()[-1]['status']=='EXIT_NO_POSITION'
    assert not w.control.read().get('entries_blocked')

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


def test_ranked_mode_buys_and_exits_only_selected_contract(tmp_path,monkeypatch):
    import market_lab.hilega_upstox_sandbox_basket_v2 as m
    from market_lab.hilega_v2_alignment_replay_v1 import RULES
    w,c=fixture(tmp_path);f=Fake();en=intent('ENTRY');ex=intent('EXIT',seq=12)
    policy_path=tmp_path/'approved-policy.json'
    policy_path.write_text(json.dumps(dict(version='reviewed-v1',strategy_version=RULES['version'],approved=True,
        ranked_ce_roles=[0,-1,1,-2,2],ranked_pe_roles=[-1,0,1,-2,2],max_spread_pct=5,
        min_bid_quantity=65,min_ask_quantity=65,min_volume=100,max_signal_age_seconds=120,
        max_quote_age_seconds=30,max_one_lot_premium_rupees=10000)))
    monkeypatch.setattr(m,'selector_policy_path',lambda env: str(policy_path))
    monkeypatch.setattr(m,'selector_mode',lambda env: m.RANKED_MODE)
    control=w.control.read();control.update(execution_mode=m.RANKED_MODE,
        strike_policy_sha256=hashlib.sha256(policy_path.read_bytes()).hexdigest());w.control.write(control)
    f.option_quality_quotes=lambda keys:{key:dict(bid_price=99,ask_price=100,bid_quantity=100,
        ask_quantity=100,volume=500,quote_time=NOW.isoformat()) for key in keys}
    w.process(en,[en,ex],f,c);w.process(en,[en,ex],f,c)
    assert len(f.calls)==1 and f.calls[0]['instrument_key']=='K-1'
    plans=[r for r in w.store.rows() if r['status']=='BASKET_PLANNED']
    assert len(plans)==1 and plans[0]['strike_selection']['selected']['role']==-1
    w.process(ex,[en,ex],f,c)
    assert len(f.calls)==2 and f.calls[1]['instrument_key']=='K-1' and f.calls[1]['transaction_type']=='SELL'


def test_ranked_mode_declines_incomplete_quote_and_exit_has_no_position(tmp_path,monkeypatch):
    import market_lab.hilega_upstox_sandbox_basket_v2 as m
    from market_lab.hilega_v2_alignment_replay_v1 import RULES
    w,c=fixture(tmp_path);f=Fake();en=intent('ENTRY');ex=intent('EXIT',seq=12)
    policy_path=tmp_path/'approved-policy.json'
    policy_path.write_text(json.dumps(dict(version='reviewed-v1',strategy_version=RULES['version'],approved=True,
        ranked_ce_roles=[0,-1,1,-2,2],ranked_pe_roles=[-1,0,1,-2,2],max_spread_pct=5,
        min_bid_quantity=65,min_ask_quantity=65,min_volume=100,max_signal_age_seconds=120,
        max_quote_age_seconds=30,max_one_lot_premium_rupees=10000)))
    monkeypatch.setattr(m,'selector_policy_path',lambda env: str(policy_path))
    monkeypatch.setattr(m,'selector_mode',lambda env: m.RANKED_MODE)
    control=w.control.read();control.update(execution_mode=m.RANKED_MODE,
        strike_policy_sha256=hashlib.sha256(policy_path.read_bytes()).hexdigest());w.control.write(control)
    f.option_quality_quotes=lambda keys:{}
    w.process(en,[en,ex],f,c);w.process(ex,[en,ex],f,c)
    assert not f.calls and [r['status'] for r in w.store.rows()]==['ENTRY_NOT_TRADED','EXIT_NO_POSITION']


def test_selector_mode_change_blocks_entry_but_known_exit_still_runs(tmp_path, monkeypatch):
    import market_lab.hilega_upstox_sandbox_basket_v2 as m
    w,c=fixture(tmp_path);f=Fake();en=intent('ENTRY');ex=intent('EXIT',seq=12)
    w.process(en,[en,ex],f,c)
    monkeypatch.setattr(m,'selector_mode',lambda env:m.RANKED_MODE)
    w.process(ex,[en,ex],f,c)
    assert len(f.calls)==10 and not w.store.open_legs()
    fresh=intent('ENTRY','fresh',13);w.process(fresh,[fresh],f,c)
    assert w.store.rows()[-1]['status']=='ENTRY_NOT_TRADED' and len(f.calls)==10


def test_quote_transport_failure_produces_no_position_exit(tmp_path,monkeypatch):
    w,c=fixture(tmp_path);f=Fake();en=intent('ENTRY');ex=intent('EXIT',seq=12)
    def fail(*args):raise TimeoutError()
    f.resolve_five=fail
    w.process(en,[en,ex],f,c);w.process(ex,[en,ex],f,c)
    assert not f.calls and not w.control.read().get('entries_blocked')
    assert [r['status'] for r in w.store.rows()]==['ENTRY_NOT_TRADED','EXIT_NO_POSITION']


def test_frozen_plan_quantity_survives_config_change(tmp_path):
    w,c=fixture(tmp_path);f=Fake();en=intent('ENTRY')
    contracts=f.resolve_five(en['direction'],'2026-10-08')
    w.store.append(dict(en,session_date='2026-10-08',status='BASKET_PLANNED',contracts=contracts,
                       legs=[dict(contract=x,role=x['role'],quantity=65) for x in contracts]))
    w.process(en,[en],f,SimpleNamespace(lots=2))
    assert all(call['quantity']==65 for call in f.calls)
    assert len([r for r in w.store.rows() if r['status']=='BASKET_PLANNED'])==1


def test_observation_mode_records_unapproved_policy_without_orders(tmp_path,monkeypatch):
    import market_lab.hilega_upstox_sandbox_basket_v2 as m
    from market_lab.hilega_v2_alignment_replay_v1 import RULES
    w,c=fixture(tmp_path);f=Fake();en=intent('ENTRY');ex=intent('EXIT',seq=12)
    path=tmp_path/'observation.json'
    path.write_text(json.dumps(dict(version='observation-example',strategy_version=RULES['version'],approved=False,
        ranked_ce_roles=[0,-1,1,-2,2],ranked_pe_roles=[0,1,-1,2,-2],max_spread_pct=5,
        min_bid_quantity=65,min_ask_quantity=65,min_volume=0,max_signal_age_seconds=120,
        max_quote_age_seconds=30,max_one_lot_premium_rupees=10000)))
    monkeypatch.setattr(m,'selector_policy_path',lambda env:str(path))
    monkeypatch.setattr(m,'selector_mode',lambda env:m.OBSERVE_MODE)
    control=w.control.read();control.update(execution_mode=m.OBSERVE_MODE,strike_policy_sha256=hashlib.sha256(path.read_bytes()).hexdigest());w.control.write(control)
    f.option_quality_quotes=lambda keys:{key:dict(bid_price=99,ask_price=100,bid_quantity=100,
        ask_quantity=100,volume=500,quote_time=NOW.isoformat()) for key in keys}
    w.process(en,[en,ex],f,c);w.process(ex,[en,ex],f,c)
    assert not f.calls
    decision=w.store.rows()[0]
    assert decision['reason']=='RANKING_OBSERVATION_ONLY'
    assert decision['strike_selection']['observation_only'] is True
    assert decision['strike_selection']['execution_approved'] is False
