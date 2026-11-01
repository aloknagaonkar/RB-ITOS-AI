from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from unittest.mock import Mock,patch
import pytest
from existing_request_attempt_v1 import submit_existing_candidate,ADOPTIONS,CLAIMS
from test_hilega_application_preparation_v1 import env,counts
from test_hilega_atomic_disabled_binding_v1 import bound_env
from test_durable_closed_handoff_v1 import ready,run as closed_handoff
from market_lab.hilega_execution_port_v1 import adapter as port
from hilega_application_preparation_fixtures import PIN

@pytest.fixture
def case(ready):
    e=ready;closed_handoff(e)
    e['token']=Mock(side_effect=AssertionError('No credentials'))
    e['transport']=port.HttpTransport(e['token'])
    e['adapter']=port.Adapter(e['adapter_store'],e['transport'])
    e['authority']=dict(account_scope=PIN['scope'],authority_id='synthetic-independent-authority',key='22'*32)
    return e

def run(e,**kwargs):
    options=dict(journal=e['path'],request_id=e['key'],capture_provider=lambda:e['data'],
                 clock=lambda:e['clock'][0],expected_version=e['version'],bridge_run_id='synthetic-lease')
    options.update(kwargs)
    return submit_existing_candidate(e['store'],e['adapter'],PIN,e['authority'],**options)

def receipt(e,aid,wire):
    return dict(attempt_id=aid,wire_fingerprint=port.sha(wire),http_status=200,
        origin='LOCAL_HTTP_TRANSPORT',body=dict(status='success',data=dict(order_ids=['SYNTHETIC-ADOPTED-ORDER'])))

def state(e):
    result=[]
    for store,tables in [(e['store'],[ADOPTIONS]),(e['adapter_store'],[CLAIMS,'attempts'])]:
        with store.db() if store is e['store'] else store.tx() as db:
            for table in tables:
                exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
                result.append(db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] if exists else 0)
    return tuple(result)

def intercept(e):
    return patch.object(e['transport'],'check',return_value=None)

def test_actual_hard_gate_precedes_capture_claim_and_send(case):
    provider=Mock(side_effect=AssertionError('No gate-closed capture'))
    with patch.object(case['transport'],'send',side_effect=AssertionError('No network')):
        result=run(case,capture_provider=provider)
    assert result['status']=='PRODUCTION_MUTATIONS_CLOSED_IN_CODE'
    provider.assert_not_called();case['token'].assert_not_called()
    assert state(case)==(0,0,0)

def test_actual_source_existing_request_is_adopted_once_in_intercepted_branch(case):
    original=case['adapter_store'].requests()[0]
    with intercept(case),patch.object(case['transport'],'send',side_effect=lambda aid,wire:receipt(case,aid,wire)) as send:
        result=run(case)
    assert result['adapter_result']['state']=='ACKNOWLEDGED_NOT_FILLED'
    assert state(case)==(1,1,1) and counts(case)==(1,1,1,0,0,0)
    assert case['adapter_store'].requests()[0]['draft']==original['draft']
    send.assert_called_once();case['token'].assert_not_called()

@pytest.mark.parametrize('point',['AFTER_AUTHORIZATION_CLAIM','AFTER_ATTEMPT_INSERT'])
def test_claim_attempt_and_adoption_roll_back_together(case,point):
    class Interrupted(BaseException):pass
    def stop(at):
        if at==point:raise Interrupted()
    with intercept(case),patch.object(case['transport'],'send',side_effect=AssertionError('No send')):
        with pytest.raises(Interrupted):run(case,checkpoint=stop)
    assert state(case)==(0,0,0)
    assert case['adapter_store'].requests()[0]['state']=='PREPARED'

@pytest.mark.parametrize('point',['AFTER_ATTEMPT_COMMIT','AFTER_TRANSPORT_BEFORE_RECEIPT','AFTER_RECEIPT_COMMIT'])
def test_restart_never_recaptures_or_resends(case,point):
    class Interrupted(BaseException):pass
    def stop(at):
        if at==point:raise Interrupted()
    with intercept(case),patch.object(case['transport'],'send',side_effect=lambda aid,wire:receipt(case,aid,wire)):
        with pytest.raises(Interrupted):run(case,checkpoint=stop)
    provider=Mock(side_effect=AssertionError('No restart capture'))
    with patch.object(case['transport'],'send',side_effect=AssertionError('No resubmit')):
        result=run(case,capture_provider=provider,clock=lambda:case['clock'][0]+timedelta(hours=2))
    assert result['recovery_only'] is True and state(case)==(1,1,1)
    provider.assert_not_called();case['token'].assert_not_called()

def test_lost_broker_response_stays_unknown_without_resubmission(case):
    with intercept(case),patch.object(case['transport'],'send',side_effect=TimeoutError('synthetic accepted response lost')) as send:
        first=run(case);second=run(case,capture_provider=Mock(side_effect=AssertionError('No repeat capture')))
    assert first['status']=='ADOPTED_BUY_UNKNOWN_NO_RESUBMISSION'
    assert second['recovery_only'] is True and state(case)==(1,1,1)
    assert case['adapter_store'].requests()[0]['state']=='UNKNOWN'
    send.assert_called_once()

def test_concurrent_callers_commit_one_claim_and_send_once(case):
    with intercept(case),patch.object(case['transport'],'send',side_effect=lambda aid,wire:receipt(case,aid,wire)) as send:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:run(case),range(2)))
    assert sum(r['new_attempt_created'] for r in results)==1
    assert state(case)==(1,1,1);send.assert_called_once()

def test_expiry_after_grant_creates_no_claim_or_attempt(case):
    now=case['clock'][0]
    def stop(at):
        if at=='AFTER_CANDIDATE_GRANT':case['clock'][0]=now+timedelta(seconds=10)
    with intercept(case):
        with pytest.raises(ValueError,match='CANDIDATE_GRANT_EXPIRED_OR_FUTURE'):run(case,checkpoint=stop)
    assert state(case)==(0,0,0)

def test_expiry_after_claim_rolls_back_everything(case):
    now=case['clock'][0]
    def stop(at):
        if at=='AFTER_AUTHORIZATION_CLAIM':case['clock'][0]=now+timedelta(seconds=10)
    with intercept(case):
        with pytest.raises(ValueError,match='CANDIDATE_GRANT_EXPIRED_OR_FUTURE'):run(case,checkpoint=stop)
    assert state(case)==(0,0,0)

def test_control_change_during_capture_prevents_adoption(case):
    def provider():
        with case['store'].db() as db:
            row=json.loads(db.execute('SELECT data FROM control WHERE id=1').fetchone()[0]);row['version']+=1
            db.execute('UPDATE control SET data=? WHERE id=1',(json.dumps(row),))
        return case['data']
    with intercept(case):
        with pytest.raises(ValueError,match='HANDOFF_CONTROL_VERSION_CHANGED'):run(case,capture_provider=provider)
    assert state(case)==(0,0,0)

def test_capture_signing_key_is_not_execution_authority(case):
    case['authority']['key']=PIN['key']
    with pytest.raises(ValueError,match='INDEPENDENT_CANDIDATE_AUTHORITY_REQUIRED'):run(case)
    assert state(case)==(0,0,0)

def test_missing_closed_receipt_cannot_adopt(case):
    from durable_closed_handoff_v1 import TABLE
    with case['store'].db() as db:db.execute('DELETE FROM '+TABLE)
    with intercept(case):
        with pytest.raises(ValueError,match='DURABLE_CLOSED_HANDOFF_REQUIRED'):run(case)
    assert state(case)==(0,0,0)

@pytest.mark.parametrize('which',['application','claim'])
def test_tampered_adoption_or_claim_blocks_recovery(case,which):
    with intercept(case),patch.object(case['transport'],'send',side_effect=lambda aid,wire:receipt(case,aid,wire)):
        run(case)
    store=case['store'] if which=='application' else case['adapter_store']
    table=ADOPTIONS if which=='application' else CLAIMS
    with store.db() if which=='application' else store.tx() as db:
        row=json.loads(db.execute('SELECT data FROM '+table).fetchone()[0]);row['signature']='changed'
        db.execute('UPDATE '+table+' SET data=?',(json.dumps(row),))
    with pytest.raises(ValueError,match='ADOPTION_SIGNATURE_INVALID'):run(case)
    assert state(case)==(1,1,1)

def test_existing_receipt_is_not_itself_execution_clearance(case):
    assert state(case)==(0,0,0)
    assert run(case)['new_attempt_created'] is False
    assert state(case)==(0,0,0)
