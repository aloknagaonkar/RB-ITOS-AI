"""All records are explicitly synthetic, including HTTP-labelled test receipts.
These tests establish validation behavior, never real broker provenance.
"""
import copy
import json
import sqlite3
from datetime import datetime,timedelta,timezone
import pytest
from link import assess, dependencies, digest, AssessmentJournal, Blocked, ROOT
from market_lab.hilega_production_account_adapter_v1 import MODEL,LIVE,sign

T = datetime(2026,10,26,4,0,tzinfo=timezone.utc)
PIN = dict(scope='UPSTOX:'+'b'*64,key='a'*64)


def put(path, table, key, value):
    with sqlite3.connect(path) as db:
        db.execute('UPDATE '+table+' SET data=? WHERE id=?',(json.dumps(value),key))


def get(path, table, key):
    with sqlite3.connect(path) as db:
        return json.loads(db.execute('SELECT data FROM '+table+' WHERE id=?',(key,)).fetchone()[0])


@pytest.fixture
def env(tmp_path):
    controller=tmp_path/'controller.sqlite';adapter=tmp_path/'adapter.sqlite';review=tmp_path/'review'
    at=T.isoformat();end=(T+timedelta(seconds=2)).isoformat()
    intent=dict(id='req',signal_id='signal',signal_at=at,side='BUY',instrument='NSE_FO|synthetic',quantity=65)
    hold=dict(id='req',instrument=intent['instrument'],quantity=65,held_cents=660000)
    body=dict(instrument_token=intent['instrument'],product='I',transaction_type='BUY',quantity=65)
    draft=dict(model='HILEGA_DISABLED_UPSTOX_REQUEST_DRAFT_V1',request_id='req',created_at=at,
        documented_method='POST',documented_host='api-hft.upstox.com',documented_path='/v3/order/place',
        body=body,fingerprint=digest(body),submission_enabled=False,entry_permission=False,orders_sent=False)
    plan=dict(request_id='req',draft=draft,signal_id='signal',signal_at=at,direction='BULLISH',reservation_reference='req')
    wire=dict(method='POST',host='api-hft.upstox.com',path='/v3/order/place',body=body)
    attempt=dict(attempt_id='attempt',request_id='req',operation='PLACE',wire=wire,retry_allowed=False)
    receipt=dict(origin='LOCAL_HTTP_TRANSPORT',attempt_id='attempt',wire_fingerprint=digest(wire),
                 http_status=200,body=dict(status='success',data=dict(order_ids=['broker-order'])))
    with sqlite3.connect(controller) as db:
        db.executescript('CREATE TABLE intents(id TEXT PRIMARY KEY,data TEXT); CREATE TABLE sim_allocation_reservations(id TEXT PRIMARY KEY,data TEXT);')
        db.execute('INSERT INTO intents VALUES(?,?)',('req',json.dumps(intent)))
        db.execute('INSERT INTO sim_allocation_reservations VALUES(?,?)',('req',json.dumps(hold)))
    with sqlite3.connect(adapter) as db:
        db.executescript('CREATE TABLE meta(id INTEGER PRIMARY KEY,data TEXT); CREATE TABLE requests(id TEXT PRIMARY KEY,fingerprint TEXT,data TEXT); CREATE TABLE attempts(id TEXT PRIMARY KEY,request_id TEXT,operation TEXT,data TEXT); CREATE TABLE receipts(id TEXT PRIMARY KEY,data TEXT);')
        db.execute('INSERT INTO meta VALUES(1,?)',(json.dumps(dict(scope=PIN['scope'],mode='LIVE_CLOSED')),))
        db.execute('INSERT INTO requests VALUES(?,?,?)',('req',digest(plan),json.dumps(dict(plan,order_id='broker-order'))))
        db.execute('INSERT INTO attempts VALUES(?,?,?,?)',('attempt','req','PLACE',json.dumps(attempt)))
        db.execute('INSERT INTO receipts VALUES(?,?)',('attempt',json.dumps(receipt)))
    report=dict(model=MODEL,evidence_mode=LIVE,generated_at=end,completed_at=end,
        session_date='2026-10-26',snapshot_id='capture',account_scope=PIN['scope'],
        status='READ_ONLY_CAPTURED',account_identity_verified=True,production_execution_enabled=False,
        entry_permission=False,orders_sent=False,orders=[dict(order_id='broker-order',instrument=intent['instrument'],
        product='I',side='BUY',quantity=65,filled=0,pending=65,status='OPEN',placed_at=at)],
        trades=[],positions=[],account_position_rows_complete=True,diagnostics={})
    report['signature']=sign(report,PIN)
    continuity=dependencies()
    journal=continuity.Journal(review,PIN)
    result=journal.record(report,as_of=end)
    assert result['status']=='READ_ONLY_REVIEWED'
    return dict(controller=controller,adapter=adapter,review=review,report=report,as_of=end,tmp=tmp_path)


def run(env, **kwargs):
    return assess(env['controller'],env['adapter'],env['review'],PIN,
                  as_of=kwargs.get('as_of',env['as_of']))


def test_chain_without_fills_is_not_exposure_or_authority(env):
    result=run(env)
    assert result['status']=='LOCAL_CHAIN_CONSISTENT_AUTHORITY_NOT_GRANTED'
    assert result['links'][0]['filled_quantity']==0
    for key in ('strategy_ownership_verified','reservation_release_permission','entry_permission',
                'production_execution_enabled','orders_sent','application_ledger_updated',
                'real_funds_reservation_verified','external_exit_attribution_verified','source_atomic'):
        assert result[key] is False


def test_sources_unchanged(env):
    paths=[env['controller'],env['adapter'],env['review']/'evidence.sqlite3']
    before=[p.read_bytes() for p in paths]
    run(env)
    assert before==[p.read_bytes() for p in paths]


@pytest.mark.parametrize('table,reason',[
    ('receipts','DURABLE_PLACE_RECEIPT_REQUIRED_NO_ADOPTION'),
    ('attempts','DURABLE_PLACE_ATTEMPT_REQUIRED'),
    ('requests','NO_DURABLE_ADAPTER_INTENTS')])
def test_missing_chain_never_adopts_matching_order(env,table,reason):
    with sqlite3.connect(env['adapter']) as db:db.execute('DELETE FROM '+table)
    result=run(env)
    assert result['reason']==reason and result['links']==[]


def test_fixture_receipt_cannot_be_relabelled_live(env):
    receipt=get(env['adapter'],'receipts','attempt');receipt['origin']='EXPLICIT_FIXTURE_TRANSPORT'
    put(env['adapter'],'receipts','attempt',receipt)
    assert run(env)['reason']=='LOCAL_TRANSPORT_RECEIPT_CHAIN_INVALID'


def test_offline_store_rejected(env):
    put(env['adapter'],'meta',1,dict(scope=PIN['scope'],mode='OFFLINE_FIXTURE'))
    assert run(env)['reason']=='LIVE_PINNED_ADAPTER_STORE_REQUIRED'


def test_other_account_rejected(env):
    put(env['adapter'],'meta',1,dict(scope='UPSTOX:'+'c'*64,mode='LIVE_CLOSED'))
    assert run(env)['reason']=='LIVE_PINNED_ADAPTER_STORE_REQUIRED'


def test_request_tampering(env):
    request=get(env['adapter'],'requests','req');request['draft']['body']['quantity']=20
    put(env['adapter'],'requests','req',request)
    assert run(env)['reason']=='REQUEST_FINGERPRINT_INVALID'


def test_wire_tampering(env):
    attempt=get(env['adapter'],'attempts','attempt');attempt['wire']['path']='/other'
    put(env['adapter'],'attempts','attempt',attempt)
    assert run(env)['reason']=='ATTEMPT_REQUEST_WIRE_MISMATCH'


def test_split_ack_rejected(env):
    receipt=get(env['adapter'],'receipts','attempt');receipt['body']['data']['order_ids'].append('second')
    put(env['adapter'],'receipts','attempt',receipt)
    assert run(env)['reason']=='ACK_UNKNOWN_OR_SPLIT_REQUIRES_REVIEW'


def test_manual_order_id_change_rejected(env):
    request=get(env['adapter'],'requests','req');request['order_id']='arbitrary'
    put(env['adapter'],'requests','req',request)
    assert run(env)['reason']=='PERSISTED_ACK_ORDER_BINDING_REQUIRED'


def test_missing_controller_intent(env):
    with sqlite3.connect(env['controller']) as db:db.execute('DELETE FROM intents')
    assert run(env)['reason']=='DURABLE_CONTROLLER_INTENT_AND_RESERVATION_REQUIRED'


def test_simulator_mapping_not_real_instrument(env):
    intent=get(env['controller'],'intents','req');intent['instrument']='SIMULATOR|CE'
    put(env['controller'],'intents','req',intent)
    assert run(env)['reason']=='CONTROLLER_INTENT_RESERVATION_MISMATCH'


def test_released_hold_cannot_be_reused(env):
    hold=get(env['controller'],'sim_allocation_reservations','req');hold['held_cents']=0
    put(env['controller'],'sim_allocation_reservations','req',hold)
    assert run(env)['reason']=='HELD_RESERVATION_REQUIRED'


def test_stale_capture(env):
    assert run(env,as_of=(T+timedelta(seconds=33)).isoformat())['reason']=='SNAPSHOT_STALE_OR_FUTURE'


def test_latest_failure_blocks_old_success(env):
    path=env['review']/'evidence.sqlite3';state=get(path,'review_state',1)
    state['status']='REVIEW_REQUIRED';put(path,'review_state',1,state)
    assert run(env)['reason']=='LATEST_REVIEW_NOT_SUCCESSFUL'


def test_capture_content_changed(env):
    path=env['review']/'evidence.sqlite3'
    with sqlite3.connect(path) as db:db.execute("UPDATE captures SET digest='changed'")
    assert run(env)['reason']=='CAPTURE_CONTENT_CHANGED'


def test_readonly_missing_source_not_created(env):
    env['controller'].unlink()
    assert run(env)['status']=='BLOCKED'
    assert not env['controller'].exists()


def test_journal_restart_and_failure_current(env):
    journal=AssessmentJournal(env['tmp']/'output',PIN,'2026-10-26',source_paths=[env['controller'],env['adapter']])
    good=run(env);journal.record(good)
    journal=AssessmentJournal(env['tmp']/'output',PIN,'2026-10-26',source_paths=[env['controller']])
    journal.record(good)
    bad=run(env,as_of=(T+timedelta(seconds=33)).isoformat());journal.record(bad)
    with sqlite3.connect(journal.path) as db:
        assert db.execute('SELECT COUNT(*) FROM bindings').fetchone()[0]==1
        assert json.loads(db.execute('SELECT data FROM assessments ORDER BY seq DESC LIMIT 1').fetchone()[0])['status']=='BLOCKED'


def test_journal_conflict_never_overwrites(env):
    journal=AssessmentJournal(env['tmp']/'output',PIN,'2026-10-26',source_paths=[env['controller']])
    result=run(env);journal.record(result);changed=copy.deepcopy(result)
    changed['links'][0]['order_id']='changed'
    assert journal.record(changed)['reason']=='DURABLE_LINK_CONFLICT'
    with sqlite3.connect(journal.path) as db:
        assert db.execute('SELECT order_id FROM bindings').fetchone()[0]=='broker-order'


def test_output_cannot_share_source_directory(env):
    with pytest.raises(Blocked):
        AssessmentJournal(env['tmp'],PIN,'2026-10-26',source_paths=[env['controller']])


def test_new_session_cannot_reuse_journal(env):
    path=env['tmp']/'output'
    AssessmentJournal(path,PIN,'2026-10-26',source_paths=[env['controller']])
    with pytest.raises(Blocked):AssessmentJournal(path,PIN,'2026-10-27',source_paths=[env['controller']])


def next_capture(env, *, filled=20):
    report=copy.deepcopy(env['report'])
    report.pop('signature')
    at=(T+timedelta(seconds=4)).isoformat()
    report.update(snapshot_id='capture-2',generated_at=at,completed_at=at)
    report['orders'][0].update(filled=filled,pending=65-filled,status='FILLED' if filled==65 else 'PARTIAL')
    report['trades']=[dict(order_id='broker-order',trade_id='synthetic-fill',instrument='NSE_FO|synthetic',
        product='I',side='BUY',quantity=filled,price='100',filled_at=(T+timedelta(seconds=3)).isoformat())]
    report['positions']=[dict(instrument='NSE_FO|synthetic',product='I',quantity=filled)]
    report['signature']=sign(report,PIN)
    result=dependencies().Journal(env['review'],PIN).record(report,as_of=at)
    assert result['status']=='READ_ONLY_REVIEWED'
    env['as_of']=at
    return report


@pytest.mark.parametrize('filled',[20,65])
def test_explicit_partial_and_full_fills(env,filled):
    next_capture(env,filled=filled)
    result=run(env)
    assert result['links'][0]['filled_quantity']==filled
    assert result['links'][0]['fill_count']==1
    assert result['strategy_ownership_verified'] is False
    assert result['reservation_release_permission'] is False


def test_empty_position_cannot_close_bound_entry(env):
    report=next_capture(env)
    report.pop('signature');report['snapshot_id']='capture-3'
    at=(T+timedelta(seconds=6)).isoformat()
    report.update(generated_at=at,completed_at=at,positions=[])
    report['signature']=sign(report,PIN)
    result=dependencies().Journal(env['review'],PIN).record(report,as_of=at)
    assert result['status']=='REVIEW_REQUIRED'
    env['as_of']=at
    assert run(env)['reason']=='LATEST_REVIEW_NOT_SUCCESSFUL'


def test_signed_capture_signature_rechecked_even_if_digest_updated(env):
    path=env['review']/'evidence.sqlite3'
    report=copy.deepcopy(env['report']);report['diagnostics']={'tampered':True}
    with sqlite3.connect(path) as db:
        db.execute('UPDATE captures SET digest=?,data=?',(digest(report),json.dumps(report)))
    assert run(env)['reason']=='SNAPSHOT_SIGNATURE_INVALID'


def test_source_row_primary_key_mismatch(env):
    intent=get(env['controller'],'intents','req');intent['id']='other'
    put(env['controller'],'intents','req',intent)
    assert run(env)['reason']=='SOURCE_ROW_ID_MISMATCH'
