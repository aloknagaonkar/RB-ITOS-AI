#!/usr/bin/env python3
"""Install an ENTRY freshness guard and offline execution-contract tests.

Run from the repository root. --check is read-only; --test stages files in a
temporary directory and runs pytest without network access. No broker calls,
service starts, arming, strategy changes or journal migration are performed.
The 120-second dispatch age is an operational ceiling, not a strategy wait.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

HELPER = '''"""Reject delayed new BUY submissions, never delay a position exit."""
from datetime import datetime

MAX_ENTRY_DISPATCH_AGE_SECONDS = 120

def entry_dispatch_check(signal_time, evaluated_at, session_date):
    result = dict(signal_time=signal_time, evaluated_at=evaluated_at.isoformat(),
                  max_age_seconds=MAX_ENTRY_DISPATCH_AGE_SECONDS,
                  policy_version='ENTRY_DISPATCH_FRESHNESS_V1')
    try:
        signal = datetime.fromisoformat(signal_time)
        if signal.utcoffset() is None or evaluated_at.utcoffset() is None:
            raise ValueError('timezone required')
        age = (evaluated_at - signal).total_seconds()
        result['age_seconds'] = age
        local_signal = signal.astimezone(evaluated_at.tzinfo)
        if local_signal.date().isoformat() != session_date:
            reason = 'ENTRY_SESSION_DATE_MISMATCH'
        elif age < 0:
            reason = 'ENTRY_TIMESTAMP_IN_FUTURE'
        elif age > MAX_ENTRY_DISPATCH_AGE_SECONDS:
            reason = 'STALE_ENTRY_DISPATCH'
        else:
            reason = None
    except (TypeError, ValueError, OverflowError):
        reason = 'INVALID_ENTRY_TIMESTAMP'
    result.update(passed=reason is None, reason=reason)
    return result
'''

TESTS = '''"""Offline tests only; fake HTTP transport cannot send orders."""
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
'''

TARGET = Path('backend/market_lab/hilega_upstox_sandbox_basket_v2.py')
IMPORT = 'from .hilega_entry_dispatch_guard_v1 import entry_dispatch_check\n'
ANCHOR = "        if intent['event_type']=='ENTRY':\n            if selector_mode(self.env)!=mode:"
GATE = """        if intent['event_type']=='ENTRY':
            dispatch_check=entry_dispatch_check(intent['event_timestamp'],self.clock(),c['session_date'])
            if not dispatch_check['passed']:
                self.store.append(dict(base,status='ENTRY_NOT_TRADED',terminal=True,reason=dispatch_check['reason'],dispatch_freshness=dispatch_check));return
            if selector_mode(self.env)!=mode:"""
PRE_REQUEST = "            request=dict(base,request_id=request_id,role=leg['role'],contract=contract,quantity=leg['quantity'],transaction_type=transaction,"
PRE_GATE = """            if transaction=='BUY':
                dispatch_check=entry_dispatch_check(intent['event_timestamp'],self.clock(),c['session_date'])
                if not dispatch_check['passed']:
                    self.store.append(dict(base,status='ENTRY_NOT_TRADED',terminal=True,reason=dispatch_check['reason'],dispatch_freshness=dispatch_check));return
"""

def replacements(root):
    p=root/TARGET
    text=p.read_text()
    if IMPORT not in text:
        anchor='from .hilega_strike_selector_v1 import StrikePolicy, rank_strikes\n'
        if text.count(anchor)!=1 or text.count(ANCHOR)!=1 or text.count(PRE_REQUEST)!=1:
            raise ValueError('SOURCE_DIFFERS: no files changed; provide current basket worker source')
        text=text.replace(anchor,anchor+IMPORT,1).replace(ANCHOR,GATE,1).replace(PRE_REQUEST,PRE_GATE+PRE_REQUEST,1)
    elif GATE not in text or PRE_GATE not in text:
        raise ValueError('INCOMPLETE_EXISTING_GUARD: no files changed')
    files={str(TARGET):text,
           'backend/market_lab/hilega_entry_dispatch_guard_v1.py':HELPER,
           'tests/test_hilega_execution_dispatch_validation.py':TESTS}
    for name,content in files.items(): compile(content,name,'exec')
    return files

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    g=ap.add_mutually_exclusive_group();g.add_argument('--check',action='store_true');g.add_argument('--test',action='store_true')
    args=ap.parse_args();root=Path.cwd();files=replacements(root)
    print(json.dumps(dict(status='VALIDATED',files=list(files),orders_sent=False,tests_run=False,max_entry_age_seconds=120)),flush=True)
    if args.check:return
    if args.test:
        with tempfile.TemporaryDirectory(prefix='hilega-dispatch-validation-') as temp:
            stage=Path(temp)
            for name,content in files.items():
                out=stage/name;out.parent.mkdir(parents=True,exist_ok=True);out.write_text(content)
            # Existing project supplies dependencies. Redirect only market_lab's
            # module lookup to staged patched files ahead of installed sources.
            (stage/'conftest.py').write_text('import market_lab\nmarket_lab.__path__.insert(0, '+repr(str(stage/'backend/market_lab'))+')\n')
            env=dict(os.environ,PYTHONPATH=str(root/'backend')+os.pathsep+str(root))
            tests=[str(stage/'tests/test_hilega_execution_dispatch_validation.py')]
            for name in ('test_hilega_sandbox_fill_ledger_v1.py','test_hilega_upstox_sandbox_basket_v2.py','test_hilega_sandbox_lifecycle_display.py'):
                src=root/'tests'/name
                if not src.exists():raise ValueError('REQUIRED_VM_TEST_MISSING: '+str(src))
                shutil.copy2(src,stage/'tests'/name);tests.append(str(stage/'tests'/name))
            result=subprocess.run([sys.executable,'-m','pytest','-q',*tests],cwd=stage,env=env)
            raise SystemExit(result.returncode)
    # Require the caller to stop the worker before installation. Do not infer
    # broker flatness from a PID or from acknowledged order counts.
    changed={k:v for k,v in files.items() if not (root/k).exists() or (root/k).read_text()!=v}
    if not changed:
        print(json.dumps(dict(status='ALREADY_APPLIED',orders_sent=False)));return
    backup=root/'backups'/('entry-dispatch-guard-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    for name in changed:
        src=root/name
        if src.exists():
            dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
    manifest={name:hashlib.sha256(content.encode()).hexdigest() for name,content in changed.items()}
    backup.mkdir(parents=True,exist_ok=True);(backup/'installed-sha256.json').write_text(json.dumps(manifest,indent=2))
    for name,content in changed.items():
        dest=root/name;dest.parent.mkdir(parents=True,exist_ok=True)
        temporary=dest.with_name(dest.name+'.dispatch-guard.tmp')
        with temporary.open('w') as handle:
            handle.write(content);handle.flush();os.fsync(handle.fileno())
        os.replace(temporary,dest)
    print(json.dumps(dict(status='APPLIED',backup=str(backup),orders_sent=False,services_started=False,tests_run=False,live_execution_enabled=False)))

if __name__=='__main__':main()
