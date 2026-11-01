"""Offline tests only; fake HTTP transport cannot send orders."""
from datetime import datetime, timedelta
import json
from types import SimpleNamespace
import httpx
import pytest
from market_lab.hilega_entry_dispatch_guard_v1 import entry_dispatch_check
from market_lab.hilega_upstox_sandbox_execution_v1 import UpstoxTransport
from market_lab.hilega_upstox_sandbox_basket_v2 import BasketWorker

AT = datetime.fromisoformat('2026-10-16T12:00:00+05:30')

@pytest.mark.parametrize('seconds,passed,reason', [
    (0,True,None),(120,True,None),(121,False,'STALE_ENTRY_DISPATCH'),
    (3180,False,'STALE_ENTRY_DISPATCH'),(-1,False,'ENTRY_TIMESTAMP_IN_FUTURE')])
def test_age_boundary(seconds,passed,reason):
    r=entry_dispatch_check((AT-timedelta(seconds=seconds)).isoformat(),AT,'2026-10-16')
    assert r['passed'] is passed and r['reason']==reason

@pytest.mark.parametrize('value', [None,'broken','2026-10-16T12:00:00'])
def test_invalid_timestamp(value):
    assert entry_dispatch_check(value,AT,'2026-10-16')['reason']=='INVALID_ENTRY_TIMESTAMP'

def test_previous_session_rejected():
    assert entry_dispatch_check('2026-10-15T12:00:00+05:30',AT,'2026-10-16')['reason']=='ENTRY_SESSION_DATE_MISMATCH'

@pytest.mark.parametrize('side',['BUY','SELL'])
def test_real_adapter_payload_with_fake_http(side):
    seen=[]
    def handler(req):
        seen.append(req)
        return httpx.Response(200,json={'status':'success','data':{'order_ids':['sandbox-test-id']}})
    # Bypass __init__; both clients use MockTransport, never real connections.
    tr=object.__new__(UpstoxTransport)
    tr.sandbox=httpx.Client(base_url='https://api-sandbox.upstox.com',transport=httpx.MockTransport(handler))
    try:
        result=tr.place_market(instrument_key='NSE_FO|TEST',quantity=65,transaction_type=side,tag='unit-test')
    finally:
        tr.sandbox.close()
    assert result=='sandbox-test-id' and len(seen)==1
    req=seen[0]; p=json.loads(req.content)
    assert str(req.url)=='https://api-sandbox.upstox.com/v3/order/place' and req.method=='POST'
    assert p['transaction_type']==side and p['instrument_token']=='NSE_FO|TEST' and p['quantity']==65
    assert p['order_type']=='MARKET' and p['product']=='I' and p['validity']=='DAY'
    assert p['price']==0 and p['is_amo'] is False

def intent(kind,at):
    return dict(intent_id=kind,event_id=kind,trade_id='test',event_type=kind,
                direction='BULLISH',event_timestamp=at.isoformat(),source_sequence=11)

class Fake:
    def __init__(self): self.calls=[]; self.resolves=0
    def resolve_five(self,direction,day):
        self.resolves+=1
        return [dict(role=i,instrument_key=f'KEY{i}',lot_size=65,option_type='CE',expiry='2026-10-19') for i in range(-2,3)]
    def instrument_ltp(self,key): return 100
    def place_market(self,**kw): self.calls.append(kw); return str(len(self.calls))

def worker(tmp_path,clock=lambda:AT):
    w=BasketWorker(control=tmp_path/'control.json',journal=tmp_path/'events.jsonl',env=tmp_path/'absent.env',clock=clock)
    w.control.write(dict(session_date='2026-10-16',strategy_id='HILEGA_DIRECTIONAL_SHADOW_V1',baseline_source_sequence=0))
    return w

def test_old_recovery_entry_never_resolves_or_orders(tmp_path,monkeypatch):
    monkeypatch.setenv('HILEGA_STRIKE_SELECTOR_MODE','FIVE_ACTUAL_SANDBOX_LEGS')
    w=worker(tmp_path); p=Fake(); en=intent('ENTRY',AT-timedelta(minutes=53))
    w.process(en,[en],p,SimpleNamespace(lots=1))
    assert not p.calls and p.resolves==0
    r=w.store.rows()[-1]
    assert r['status']=='ENTRY_NOT_TRADED' and r['reason']=='STALE_ENTRY_DISPATCH'
    assert r['dispatch_freshness']['age_seconds']==3180
    w.process(en,[en],p,SimpleNamespace(lots=1))
    assert not p.calls and len(w.store.rows())==1
    ex=intent('EXIT',AT)
    w.process(ex,[en,ex],p,SimpleNamespace(lots=1))
    assert not p.calls and w.store.rows()[-1]['status']=='EXIT_NO_POSITION'

def test_fresh_entry_and_old_exit_still_work(tmp_path,monkeypatch):
    monkeypatch.setenv('HILEGA_STRIKE_SELECTOR_MODE','FIVE_ACTUAL_SANDBOX_LEGS')
    w=worker(tmp_path); p=Fake(); en=intent('ENTRY',AT)
    w.process(en,[en],p,SimpleNamespace(lots=1))
    assert len(p.calls)==5
    ex=intent('EXIT',AT-timedelta(minutes=10))
    w.process(ex,[en,ex],p,SimpleNamespace(lots=1))
    assert len(p.calls)==10 and all(x['transaction_type']=='SELL' for x in p.calls[5:])

def test_slow_contract_resolution_cannot_submit_stale_entry(tmp_path,monkeypatch):
    monkeypatch.setenv('HILEGA_STRIKE_SELECTOR_MODE','FIVE_ACTUAL_SANDBOX_LEGS')
    current=[AT]; w=worker(tmp_path,lambda:current[0]); p=Fake()
    resolve=p.resolve_five
    def slow(*args):
        current[0]=AT+timedelta(seconds=121)
        return resolve(*args)
    p.resolve_five=slow; en=intent('ENTRY',AT)
    w.process(en,[en],p,SimpleNamespace(lots=1))
    assert not p.calls and w.store.rows()[-1]['reason']=='STALE_ENTRY_DISPATCH'
