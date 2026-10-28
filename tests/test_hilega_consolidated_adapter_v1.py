import copy,os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from market_lab.hilega_execution_port_v1.adapter import Adapter,Store,FixtureTransport,HttpTransport,Blocked,OutcomeUnknown,sha
from market_lab.hilega_execution_port_v1.mapping import draft
AT='2026-10-26T09:25:00+05:30'

def request(key='entry',side='BUY'):
    c=dict(instrument_key='NSE_FO|12345',underlying_key='NSE_INDEX|Nifty 50',instrument_type='CE',segment='NSE_FO',expiry='2026-10-27',lot_size=65,minimum_lot=65,freeze_quantity=1800)
    return draft(c,request_id=key,side=side,lots=1,as_of=AT)
def prepare(a,key='entry'):
    return a.prepare(request(key),signal_id='signal-'+key,signal_at=AT,direction='BULLISH',reservation_reference='EXPLICIT_FIXTURE_HOLD_REFERENCE',as_of=AT)
@pytest.fixture
def env(tmp_path):
    store=Store(tmp_path/'fixture.sqlite','EXPLICIT_FIXTURE_SCOPE','OFFLINE_FIXTURE');t=FixtureTransport(store);a=Adapter(store,t);prepare(a);return a,t

def test_attempt_precedes_transport(env):
    a,t=env;seen=[]
    def checkpoint(stage):
        if stage=='AFTER_ATTEMPT_COMMIT':
            assert a.status()['attempts'][0]['state']=='IN_FLIGHT'
            assert not t.orders();seen.append(stage)
    a.checkpoint=checkpoint;a.submit('entry');assert seen

def test_acknowledgement_does_not_mark_filled(env):
    a,t=env;a.submit('entry');row=a.status()['requests'][0]
    assert row['state']=='ACKNOWLEDGED_NOT_FILLED' and row['filled'] is None and row['remaining'] is None
    assert a.status()['receipt_count']==1

def test_duplicate_place_never_resends(env):
    a,t=env;a.submit('entry');assert a.submit('entry')['idempotent_replay'];assert len(t.orders())==1

def test_timeout_after_acceptance_never_resends_or_adopts(env):
    a,t=env;t.timeout_after=True;assert a.submit('entry')['state']=='UNKNOWN'
    a.submit('entry');a.recover();a.reconcile_fixture()
    assert len(t.orders())==1 and a.status()['requests'][0]['order_id'] is None
    assert a.status()['requests'][0]['state']=='UNKNOWN'

def test_timeout_before_acceptance_is_still_unknown(env):
    a,t=env;t.timeout_before=True;a.submit('entry');a.recover();a.submit('entry')
    assert not t.orders() and a.status()['requests'][0]['state']=='UNKNOWN'

def test_split_ack_requires_review(env):
    a,t=env;t.split_ack=True;a.submit('entry')
    assert a.status()['requests'][0]['order_id'] is None and a.status()['requests'][0]['state']=='UNKNOWN'

def test_receipt_durable_before_binding_recovers_without_post(env):
    a,t=env
    class Stop(BaseException):pass
    def checkpoint(stage):
        if stage=='AFTER_RECEIPT_COMMIT':raise Stop()
    a.checkpoint=checkpoint
    with pytest.raises(Stop):a.submit('entry')
    assert a.status()['requests'][0]['order_id'] is None and a.status()['receipt_count']==1
    other=Adapter(a.store,FixtureTransport(a.store));other.recover()
    assert other.status()['requests'][0]['order_id'] and other.status()['requests'][0]['state']=='RECONCILIATION_REQUIRED'
    other.submit('entry');assert len(t.orders())==1

def test_loss_before_receipt_is_unknown_not_recoverable_by_tag(env):
    a,t=env
    class Stop(BaseException):pass
    a.checkpoint=lambda stage: (_ for _ in ()).throw(Stop()) if stage=='AFTER_TRANSPORT_BEFORE_RECEIPT' else None
    with pytest.raises(Stop):a.submit('entry')
    a.recover();assert a.status()['requests'][0]['state']=='UNKNOWN' and len(t.orders())==1

def test_interrupt_before_post_blocks_retry(env):
    a,t=env
    class Stop(BaseException):pass
    a.checkpoint=lambda stage: (_ for _ in ()).throw(Stop()) if stage=='AFTER_ATTEMPT_COMMIT' else None
    with pytest.raises(Stop):a.submit('entry')
    a.recover();a.submit('entry');assert not t.orders()

def test_partial_fill_cancel_ack_is_not_flat(env):
    a,t=env;a.submit('entry');oid=a.status()['requests'][0]['order_id'];t.fill(oid,20)
    a.cancel('entry');assert a.status()['requests'][0]['state']=='CANCEL_ACK_RECONCILE_REQUIRED'
    a.reconcile_fixture();r=a.status()['requests'][0]
    assert r['state']=='CANCELLED' and r['filled']==20 and r['remaining'] is None
    with pytest.raises(Blocked):a.release_reservation('entry')

def test_cancel_repeated_never_reissues(env):
    a,t=env;a.submit('entry');a.cancel('entry');assert a.cancel('entry')['idempotent_replay']
    assert len(a.status()['attempts'])==2

def test_cancel_timeout_unknown_until_reconciled(env):
    a,t=env;a.submit('entry');t.cancel_timeout=True;a.cancel('entry')
    assert a.status()['requests'][0]['state']=='CANCEL_OUTCOME_UNKNOWN'
    a.cancel('entry');a.reconcile_fixture();assert a.status()['requests'][0]['state']=='CANCELLED'

def test_cancellation_requires_bound_order(env):
    a,t=env
    with pytest.raises(Blocked,match='ACKNOWLEDGED_ORDER'):a.cancel('entry')

def test_concurrent_duplicate_requests_only_one_transport_call(env):
    a,t=env
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda _:a.submit('entry'),range(2)))
    assert len(t.orders())==1 and len(a.status()['attempts'])==1

def test_wrong_scope_or_mode_rejected(env):
    a,_=env
    with pytest.raises(Blocked):Store(a.store.path,'other','OFFLINE_FIXTURE')
    with pytest.raises(Blocked):Store(a.store.path,a.store.scope,'LIVE_CLOSED')

def test_transport_subclass_not_permitted(env):
    a,_=env
    class Other(FixtureTransport):pass
    with pytest.raises(Blocked):Adapter(a.store,Other(a.store))

def test_body_fingerprint_tampering_rejected(env):
    a,_=env;r=request('other');r['body']['quantity']=130
    with pytest.raises(Blocked):a.prepare(r,signal_id='x',signal_at=AT,direction='BULLISH',reservation_reference='h',as_of=AT)

def test_public_ack_import_is_disabled(env):
    with pytest.raises(Blocked,match='CALLER_ACK'):env[0].import_acknowledgement('entry',{})

def test_live_gate_precedes_token_and_network(tmp_path,monkeypatch):
    from market_lab.hilega_execution_port_v1 import adapter as m
    calls=[]
    def never(*a,**k):calls.append('network');raise AssertionError('NETWORK_MUST_NOT_BE_CALLED')
    monkeypatch.setattr(m,'build_opener',never);monkeypatch.setattr(m,'Request',never)
    transport=HttpTransport(lambda:calls.append('token') or 'unused')
    a=Adapter(Store(tmp_path/'live-disabled.sqlite','DRAFT_SCOPE_NOT_VERIFIED','LIVE_CLOSED'),transport);prepare(a)
    monkeypatch.setenv('HILEGA_PRODUCTION_EXECUTION_ENABLED','1')
    assert a.submit('entry')['status']=='PRODUCTION_MUTATIONS_CLOSED_IN_CODE'
    assert a.cancel('entry')['status']=='PRODUCTION_MUTATIONS_CLOSED_IN_CODE'
    assert calls==[] and a.status()['attempts']==[]

def test_raw_receipt_provenance_mismatch_rejected(env):
    a,t=env;a.submit('entry');attempt=a.status()['attempts'][0]
    with pytest.raises(Blocked,match='PROVENANCE'):a._persist_receipt(attempt,dict(origin='EXPLICIT_FIXTURE_TRANSPORT',attempt_id=attempt['attempt_id'],wire_fingerprint='wrong',body={}))

def test_restart_invalidates_cached_fill_state(env):
    a,t=env;a.submit('entry');oid=a.status()['requests'][0]['order_id'];t.fill(oid,65);a.reconcile_fixture()
    assert a.status()['requests'][0]['filled']==65
    a.recover();assert a.status()['requests'][0]['filled'] is None
    a.reconcile_fixture();assert a.status()['requests'][0]['filled']==65

def test_request_id_conflict(env):
    a,t=env;r=request();r['body']['quantity']=130;r['fingerprint']=sha(r['body'])
    with pytest.raises(Blocked,match='REQUEST_ID_CONFLICT'):a.prepare(r,signal_id='signal-entry',signal_at=AT,direction='BULLISH',reservation_reference='EXPLICIT_FIXTURE_HOLD_REFERENCE',as_of=AT)

def signed_capture():
    from market_lab.hilega_production_account_adapter_v1 import (
        sign, MODEL, LIVE, normalise,
    )
    pin = dict(scope="EXPLICIT_SYNTHETIC_PIN_SCOPE", key="11" * 32)
    empty = {"status": "success", "data": []}
    normalized = normalise(empty, empty, empty, observed_at=AT)
    report = dict(
        model=MODEL, evidence_mode=LIVE, account_scope=pin["scope"],
        snapshot_id="synthetic-test-capture",
        generated_at=AT, completed_at=AT, session_date=AT[:10],
        status="READ_ONLY_CAPTURED", account_identity_verified=True,
        profile_verified_before_and_after=True, source_atomic=False,
        production_execution_enabled=False, entry_permission=False,
        orders_sent=False, **normalized,
    )
    report["signature"] = sign(report, pin)
    return report, pin

def test_read_only_empty_baseline_no_ownership_claim(tmp_path):
    cap,pin=signed_capture();a=Adapter(Store(tmp_path/'live.sqlite',pin['scope'],'LIVE_CLOSED'),HttpTransport(lambda:'unused'))
    result=a.reconcile_read_only(cap,pin,as_of=AT)
    assert result['status']=='EMPTY_READ_ONLY_BASELINE' and result['ownership_verified'] is False
    assert not a.status()['attempts']

def test_read_only_account_activity_remains_review(tmp_path):
    from market_lab.hilega_production_account_adapter_v1 import (
        sign, normalise,
    )
    cap, pin = signed_capture()
    cap.pop("signature")
    order = dict(
        order_id="unowned", instrument_token="NSE_FO|12345",
        product="I", transaction_type="BUY", quantity=65,
        filled_quantity=0, pending_quantity=65, status="open",
        order_timestamp=AT,
    )
    empty = {"status": "success", "data": []}
    cap.update(normalise(
        {"status": "success", "data": [order]},
        empty, empty, observed_at=AT,
    ))
    cap["signature"] = sign(cap, pin)
    adapter = Adapter(
        Store(tmp_path / "live.sqlite", pin["scope"], "LIVE_CLOSED"),
        HttpTransport(lambda: pytest.fail("Token must not be accessed")),
    )
    result = adapter.reconcile_read_only(cap, pin, as_of=AT)
    assert result["status"] == "READ_ONLY_OWNERSHIP_REVIEW"
    assert result["ownership_verified"] is False
    assert result["matched_known_order_count"] == 0
    terminal = result["terminal_account_review"]
    assert "NON_TERMINAL_ORDERS" in terminal["reasons"]
    assert terminal["reservation_release_permission"] is False
    assert adapter.status()["requests"] == []
    assert adapter.status()["attempts"] == []

def test_live_capture_cannot_enter_fixture(env):
    cap,pin=signed_capture()
    with pytest.raises(Blocked,match='LIVE_CAPTURE_CANNOT'):env[0].reconcile_read_only(cap,pin,as_of=AT)

def test_tampered_read_only_capture_rejected(tmp_path):
    from market_lab.hilega_production_account_adapter_v1 import AdapterBlocked
    cap,pin=signed_capture();cap['snapshot_id']='tampered'
    a=Adapter(Store(tmp_path/'live.sqlite',pin['scope'],'LIVE_CLOSED'),HttpTransport(lambda:'unused'))
    with pytest.raises(AdapterBlocked):a.reconcile_read_only(cap,pin,as_of=AT)
