import json
import pytest
from authenticated_handoff_v1 import review
from test_hilega_application_preparation_v1 import env, process, counts
from test_hilega_atomic_disabled_binding_v1 import bound_env
from hilega_application_preparation_fixtures import PIN

@pytest.fixture
def committed(bound_env):
    process(bound_env)
    bound_env['key']=bound_env['adapter_store'].requests()[0]['request_id']
    return bound_env

def run(e):
    with e['store'].lock(),e['store'].db() as db:
        db.execute('ATTACH DATABASE ? AS broker',(str(e['adapter_store'].path),))
        db.execute('BEGIN')
        before=db.total_changes
        result=review(db,PIN,journal=e['path'],request_id=e['key'])
        assert db.total_changes==before
        return result

def test_actual_atomic_source_binding_verified_without_execution(committed):
    result=run(committed)
    assert result['status']=='HISTORICAL_BOUND_PREPARATION_VERIFIED_EXECUTION_CLOSED'
    assert result['production_execution_enabled'] is False
    assert result['execution_adoption_implemented'] is False
    assert counts(committed)==(1,1,1,0,0,0)

def test_repeat_review_does_not_collect_prepare_or_send(committed):
    e=committed;calls=len(e['calls']);requests=e['adapter_store'].requests()
    assert run(e)==run(e)
    assert len(e['calls'])==calls and e['adapter_store'].requests()==requests
    with e['adapter_store'].tx() as db:
        assert db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]==0

@pytest.mark.parametrize('table,field,value,reason',[
 ('preparation_cash_reservations','signature','tampered','SIGNATURE_INVALID'),
 ('preparation_plans','quantity',999,'SIGNED_REFERENCE_CHANGED'),
 ('preparation_shadow_holds','held_cents',1,'SIGNED_REFERENCE_CHANGED'),
 ('preparation_outbox','quantity',999,'SIGNED_REFERENCE_CHANGED'),
 ('preparation_request_bindings','model','changed','APPLICATION_BINDING_CHANGED'),
 ('preparation_request_bindings','entry_permission',True,'BOUND_AUTHORITY_CHANGED'),
 ('preparation_source','hash','changed','BOUND_CURSOR_CHANGED'),
])
def test_tampered_local_reference_blocks(committed,table,field,value,reason):
    e=committed;key=1 if table=='preparation_source' else e['key']
    with e['store'].db() as db:
        row=json.loads(db.execute('SELECT data FROM '+table+' WHERE id=?',(key,)).fetchone()[0])
        row[field]=value
        db.execute('UPDATE '+table+' SET data=? WHERE id=?',(json.dumps(row),key))
    with pytest.raises(ValueError,match=reason):run(e)

def test_changed_consumption_blocks(committed):
    with committed['store'].db() as db:db.execute("UPDATE preparation_consumed SET fingerprint='changed'")
    with pytest.raises(ValueError,match='BOUND_CONSUMPTION_CHANGED'):run(committed)

def test_changed_request_blocks(committed):
    with committed['adapter_store'].tx() as db:
        key=committed['key'];row=json.loads(db.execute('SELECT data FROM requests WHERE id=?',(key,)).fetchone()[0])
        row['state']='UNKNOWN';db.execute('UPDATE requests SET data=? WHERE id=?',(json.dumps(row),key))
    with pytest.raises(ValueError,match='BOUND_REQUEST_CHANGED_OR_ALREADY_ATTEMPTED'):run(committed)

def test_tampered_journal_blocks(committed):
    p=committed['path'];row=json.loads(p.read_text().splitlines()[0]);row['record_hash']='changed'
    p.write_text(json.dumps(row)+'\n')
    with pytest.raises(Exception,match='SOURCE_CHAIN_INVALID'):run(committed)
