"""VM-only patched Source integration; every DB and signal is synthetic."""
import json
import pytest
from test_hilega_application_preparation_v1 import env,process,append,counts
from test_hilega_atomic_disabled_binding_v1 import bound_env

EXIT='STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'


def rows(e,table):
    with e['store'].db() as db:
        return [json.loads(r[0]) for r in db.execute('SELECT data FROM '+table)]


def test_entry_then_exit_keeps_deployed_reservation(bound_env):
    e=bound_env;process(e)
    before=rows(e,'preparation_cash_reservations')
    requests=e['adapter_store'].requests()
    append(e['path'],[EXIT]);e['source'].run_source_once(e['path'])
    record,=rows(e,'preparation_exit_dispatch')
    assert record['dispatch_status']=='REFUSED_CLOSED'
    assert record['exit_quantity'] is None
    assert record['automatic_execution_eligible'] is False
    assert rows(e,'preparation_cash_reservations')==before
    assert e['adapter_store'].requests()==requests
    assert counts(e)==(1,1,1,0,0,0)
    assert e['store'].control()['mode']=='PAUSED'
    with e['adapter_store'].tx() as db:
        assert db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]==0


def test_exit_without_ownership_never_calls_evidence_provider(bound_env):
    e=bound_env
    append(e['path'],[EXIT]);e['source'].run_source_once(e['path'])
    record,=rows(e,'preparation_exit_dispatch')
    assert record['parent_request_id'] is None
    assert not e['calls'] and e['adapter_store'].requests()==[]
    assert counts(e)==(0,0,0,0,0,0)
    assert e['store'].control()['mode']=='PAUSED'


def test_reversal_consumes_boundary_without_new_entry(bound_env):
    e=bound_env
    append(e['path'],[EXIT,'ENTRY_BEARISH_ROUTE_B_STRUCTURAL'])
    e['source'].run_source_once(e['path'])
    record,=rows(e,'preparation_exit_dispatch')
    assert record['reversal_entry_suppressed'] is True
    with e['store'].db() as db:
        assert db.execute('SELECT COUNT(*) FROM preparation_consumed').fetchone()[0]==2
    assert e['adapter_store'].requests()==[] and not e['calls']
    assert counts(e)==(0,0,0,0,0,0)


def test_interrupted_dispatch_restarts_once(bound_env):
    e=bound_env
    append(e['path'],[EXIT])
    class Interrupted(BaseException):pass
    def stop(point):
        if point=='BEFORE_CLOSED_EXIT_DISPATCH_COMMIT':raise Interrupted()
    e['source'].checkpoint=stop
    with pytest.raises(Interrupted):e['source'].run_source_once(e['path'])
    with e['store'].db() as db:
        assert db.execute('SELECT COUNT(*) FROM preparation_consumed').fetchone()[0]==0
    e['source'].checkpoint=lambda point:None
    e['source'].run_source_once(e['path'])
    e['source'].run_source_once(e['path'])
    assert len(rows(e,'preparation_exit_dispatch'))==1
    assert e['adapter_store'].requests()==[]
