from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from market_lab.hilega_ui_journal_cache_v1 import JournalCache
from hilega_policy_live.active_marks import metadata_worker

def append(path,row):
    with path.open('ab') as f:f.write(json.dumps(row).encode()+b'\n')

def test_initial_read_is_explicit_warming(tmp_path):
    cache=JournalCache(tmp_path/'audit.jsonl',start=False)
    with pytest.raises(HTTPException) as e:cache.read()
    assert e.value.status_code==503

def test_reads_appends_only_and_never_changes_audit(tmp_path):
    path=tmp_path/'audit.jsonl';append(path,dict(sequence=1,payload={'x':1}))
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    cache=JournalCache(path,start=False);cache.refresh();size=cache.bytes_read
    assert cache.read()==[dict(sequence=1,payload={'x':1})]
    cache.refresh();assert cache.bytes_read==size
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    append(path,dict(sequence=2,payload={'x':2}));cache.refresh()
    assert [r['sequence'] for r in cache.read()]==[1,2]
    assert cache.bytes_read==path.stat().st_size

def test_partial_tail_waits_until_complete(tmp_path):
    path=tmp_path/'audit.jsonl';append(path,dict(sequence=1))
    cache=JournalCache(path,start=False);cache.refresh();offset=cache.offset
    with path.open('ab') as f:f.write(b'{"sequence":2')
    cache.refresh();assert cache.offset==offset and len(cache.read())==1
    with path.open('ab') as f:f.write(b'}\n')
    cache.refresh();assert [r['sequence'] for r in cache.read()]==[1,2]

def test_rotation_drops_old_rows(tmp_path):
    path=tmp_path/'audit.jsonl';append(path,dict(sequence=1))
    cache=JournalCache(path,start=False);cache.refresh()
    path.rename(tmp_path/'old.jsonl');append(path,dict(sequence=99));cache.refresh()
    assert cache.read()==[dict(sequence=99)]

def test_dashboard_request_does_not_project_on_request_thread(tmp_path,monkeypatch):
    from market_lab import hilega_directional_trade_dashboard_v1 as module
    path=tmp_path/'audit.jsonl';append(path,dict(sequence=1))
    cache=JournalCache(path,start=False);cache.refresh();calls=[]
    monkeypatch.setattr(module,'project_directional_shadow_dashboard',lambda rows:calls.append(len(rows)) or dict(trades=[]))
    with pytest.raises(HTTPException):cache.read_dashboard()
    assert calls==[]
    cache.refresh_dashboard();assert calls==[1]
    assert cache.read_dashboard()==dict(trades=[])
    cache.refresh_dashboard();assert calls==[1]

def test_metadata_lookup_is_read_only_and_separate_from_ranking():
    class Response:
        def raise_for_status(self):pass
        def json(self):return dict(status='success',data=[dict(instrument_key='NSE_FO|1',lot_size=65,expiry='2026-10-27')])
    calls=[]
    def get(path,**kwargs):calls.append((path,kwargs));return Response()
    original=[dict(instrument_key='NSE_FO|2',lot_size=65)]
    publisher=SimpleNamespace(rest=SimpleNamespace(get=get),catalog=deepcopy(original))
    metadata_worker(publisher)
    assert publisher.catalog==original
    assert publisher._display_catalog['NSE_FO|1']['lot_size']==65
    assert calls[0][0]=='/v2/option/contract'
    assert publisher._display_metadata_status=='READY'

def test_metadata_failure_does_not_raise_into_observer():
    def get(*args,**kwargs):raise RuntimeError('provider unavailable')
    publisher=SimpleNamespace(rest=SimpleNamespace(get=get),catalog=[])
    metadata_worker(publisher)
    assert publisher._display_metadata_status=='UNAVAILABLE'
    assert publisher.catalog==[]
