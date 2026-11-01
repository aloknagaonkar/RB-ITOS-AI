import json
from copy import deepcopy
import sqlite3
import pytest
from closed_handoff_contract_v1 import inspect_committed
from test_hilega_application_preparation_v1 import env, process, counts

@pytest.fixture
def prepared_application(env, monkeypatch):
    monkeypatch.setenv('HILEGA_PREPARATION_ATOMIC_BINDING_ENABLED', '0')
    process(env)
    return env

def observe(e):
    with e['store'].db() as db:
        db.execute('BEGIN')
        before = db.total_changes
        result = inspect_committed(db)
        assert db.total_changes == before
        return result

def test_actual_source_committed_records_are_observed(prepared_application):
    result = observe(prepared_application)
    assert len(result['references']) == 1
    assert result['production_execution_enabled'] is False
    assert result['existing_preparation_adopted'] is False
    assert counts(prepared_application) == (1,1,1,0,0,0)

def test_observer_does_not_collect_or_prepare_again(prepared_application):
    e=prepared_application; before=len(e['calls'])
    first=observe(e); second=observe(e)
    assert first == second and len(e['calls']) == before
    assert counts(e) == (1,1,1,0,0,0)

def test_actual_source_replay_preserves_observation(prepared_application):
    e=prepared_application; before=observe(e)
    e['source'].run_source_once(e['path'])
    assert observe(e) == before and len(e['calls']) == 1

@pytest.mark.parametrize('change,reason', [
    ('authority','APPLICATION_AUTHORITY_CHANGED'),
    ('quantity','APPLICATION_CONTRACT_MISMATCH'),
    ('cursor','APPLICATION_CURSOR_HASH_MISMATCH'),
    ('missing_hold','APPLICATION_REFERENCE_SET_MISMATCH'),
    ('missing_consumption','APPLICATION_CONSUMPTION_REFERENCE_REQUIRED'),
])
def test_inconsistent_committed_references_block(prepared_application,change,reason):
    e=prepared_application
    with e['store'].db() as db:
        if change in {'authority','quantity'}:
            key,raw=db.execute('SELECT id,data FROM preparation_outbox').fetchone()
            row=json.loads(raw)
            row['entry_permission' if change=='authority' else 'quantity'] = True if change=='authority' else row['quantity']+1
            db.execute('UPDATE preparation_outbox SET data=? WHERE id=?',(json.dumps(row),key))
        elif change=='cursor':
            row=json.loads(db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()[0]);row['hash']='changed'
            db.execute('UPDATE preparation_source SET data=? WHERE id=1',(json.dumps(row),))
        elif change=='missing_hold':db.execute('DELETE FROM preparation_shadow_holds')
        else:db.execute('DELETE FROM preparation_consumed')
    with pytest.raises(ValueError,match=reason):observe(e)

def test_snapshot_required():
    with sqlite3.connect(':memory:') as db:
        with pytest.raises(ValueError,match='CALLER_SNAPSHOT_REQUIRED'):inspect_committed(db)

def test_closed_exit_record_never_becomes_execution_instruction(prepared_application):
    e=prepared_application
    with e['store'].db() as db:
        db.execute('CREATE TABLE preparation_exit_dispatch(id TEXT,data TEXT)')
        db.execute('INSERT INTO preparation_exit_dispatch VALUES(?,?)',('exit',json.dumps(dict(
            dispatch_status='REFUSED_CLOSED',automatic_execution_eligible=False,
            production_execution_enabled=False))))
    result=observe(e)
    assert result['closed_exit_record_count']==1
    assert result['automatic_execution_eligible'] is False
