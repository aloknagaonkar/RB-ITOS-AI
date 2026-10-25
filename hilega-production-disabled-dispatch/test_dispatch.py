import copy
from concurrent.futures import ThreadPoolExecutor
import pytest
from dispatch import Outbox,Blocked,sha
from provider_mapping import draft
AT='2026-10-26T09:25:00+05:30'

def request(key='entry',side='BUY'):
    contract=dict(instrument_key='NSE_FO|12345',underlying_key='NSE_INDEX|Nifty 50',instrument_type='CE',segment='NSE_FO',expiry='2026-10-27',lot_size=65,minimum_lot=65,freeze_quantity=1800)
    return draft(contract,request_id=key,side=side,lots=1,as_of=AT)
def prepare(box,key='entry',signal='s1',side='BUY',parent=None):return box.prepare(request(key,side),signal_id=signal,signal_at=AT,direction='BULLISH',as_of=AT,parent_id=parent)
@pytest.fixture
def box(tmp_path):return Outbox(tmp_path/'outbox.sqlite','OFFLINE_DRAFT_SCOPE')

def test_durable_prepare_before_refusal(box):
    prepare(box);r=box.attempt_submission('entry')
    assert r['orders_sent'] is False and r['unknown_acceptance'] is False
    assert box.status()['events'][0]['type']=='BROKER_REQUEST_PREPARED_DISABLED'
    assert box.status()['requests'][0]['order_id'] is None

def test_restart_persists_and_cannot_dispatch(box):
    prepare(box);box.attempt_submission('entry');other=Outbox(box.path,box.scope)
    assert other.status()['requests'][0]['state']=='BLOCKED_TRANSPORT_DISABLED'
    assert other.attempt_submission('entry')['retry_allowed'] is False

def test_duplicate_prepare_idempotent_after_refusal(box):
    prepare(box);box.attempt_submission('entry');row=prepare(box)
    assert row['idempotent_replay'] and len(box.status()['requests'])==1

def test_request_conflict(box):
    prepare(box)
    with pytest.raises(Blocked,match='REQUEST_ID_CONFLICT'):prepare(box,signal='different')

def test_signal_consumed_once(box):
    prepare(box)
    with pytest.raises(Blocked,match='SIGNAL_ALREADY'):prepare(box,key='other')

def test_no_bare_submission(box):
    with pytest.raises(Blocked,match='NOT_PREPARED'):box.attempt_submission('missing')

def test_scope_pinned(box):
    with pytest.raises(Blocked,match='SCOPE_MISMATCH'):Outbox(box.path,'other')

def test_environment_cannot_enable(box,monkeypatch):
    monkeypatch.setenv('HILEGA_PRODUCTION_EXECUTION_ENABLED','1');monkeypatch.setenv('UPSTOX_ACCESS_TOKEN','not-used')
    prepare(box);assert box.attempt_submission('entry')['production_execution_enabled'] is False

@pytest.mark.parametrize('method',['cancel','modify','release_reservation','import_acknowledgement'])
def test_mutations_and_manual_ack_import_disabled(box,method):
    with pytest.raises(Blocked):getattr(box,method)('entry')

def test_credentials_cannot_be_persisted_in_draft(box):
    r=request();r['Authorization']='Bearer fake'
    with pytest.raises(Blocked,match='EXACT_DISABLED_DRAFT'):box.prepare(r,signal_id='s',signal_at=AT,direction='BULLISH',as_of=AT)

def test_endpoint_cannot_change(box):
    r=request();r['documented_host']='another.example'
    with pytest.raises(Blocked,match='FIXED_DOCUMENTED_ENDPOINT'):box.prepare(r,signal_id='s',signal_at=AT,direction='BULLISH',as_of=AT)

def test_body_tamper_rejected(box):
    r=request();r['body']['quantity']=130
    with pytest.raises(Blocked,match='FINGERPRINT'):box.prepare(r,signal_id='s',signal_at=AT,direction='BULLISH',as_of=AT)

def test_stale_draft_rejected(box):
    with pytest.raises(Blocked,match='STALE'):box.prepare(request(),signal_id='s',signal_at=AT,direction='BULLISH',as_of='2026-10-26T09:26:01+05:30')

def test_exit_draft_requires_parent_but_does_not_prove_ownership(box):
    with pytest.raises(Blocked,match='EXIT_PARENT'):prepare(box,key='exit',signal='x',side='SELL')
    prepare(box);row=prepare(box,key='exit',signal='x',side='SELL',parent='entry')
    assert row['reservation_verified'] is False and row['account_identity_verified'] is False
    assert box.attempt_submission('exit')['orders_sent'] is False

def test_concurrent_duplicate_plan_creates_one_row(box):
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda _:prepare(box),range(2)))
    assert len(box.status()['requests'])==1
