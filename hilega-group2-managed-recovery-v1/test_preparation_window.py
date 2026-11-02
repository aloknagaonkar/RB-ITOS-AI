"""Synthetic fresh signals and signed evidence; application code from verified bundle."""
import json
import pytest
from test_hilega_application_preparation_v1 import env,process,counts
from test_hilega_atomic_disabled_binding_v1 import bound_env,binding_count,requests
from hilega_application_preparation_fixtures import PIN,T
from market_lab.hilega_preparation_runtime_v1.cash_reservation import verify_row
from market_lab.hilega_execution_port_v1.adapter import Adapter,HttpTransport
from datetime import timedelta

def cash_rows(e):
    with e['store'].db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='preparation_cash_reservations'").fetchone():return []
        return [json.loads(x[0]) for x in db.execute('SELECT data FROM preparation_cash_reservations')]

def test_fresh_signal_creates_disabled_atomic_preparation(bound_env):
    e=bound_env;process(e)
    assert counts(e)==(1,1,1,0,0,0) and binding_count(e)==1
    row,=requests(e);assert row['state']=='PREPARED' and row['order_id'] is None
    assert e['store'].control()['mode']=='PAUSED'

def test_cash_reference_is_signed_and_matches_request(bound_env):
    e=bound_env;process(e);row,=cash_rows(e);verify_row(row,PIN)
    request,=requests(e)
    assert row['id']==request['reservation_reference'] and row['amount_cents']<=row['cash_cap_cents']
    assert row['broker_cash_locked'] is False and row['fee_buffer_approved_for_production'] is False

def test_replay_does_not_duplicate_or_recollect(bound_env):
    e=bound_env;process(e);before=requests(e);calls=len(e['calls']);e['source'].run_source_once(e['path'])
    assert requests(e)==before and len(e['calls'])==calls and len(cash_rows(e))==1

def test_closed_gate_never_reads_transport_token(bound_env):
    e=bound_env;process(e);request,=requests(e)
    adapter=Adapter(e['adapter_store'],HttpTransport(lambda:pytest.fail('Token provider must not be called')))
    assert adapter.submit(request['request_id'])['status']=='PRODUCTION_MUTATIONS_CLOSED_IN_CODE'
    assert adapter.status()['attempts']==[]

def test_stale_signal_does_not_create_binding_or_cash(bound_env):
    e=bound_env;e['clock'][0]=T+timedelta(seconds=61);process(e)
    assert counts(e)==(0,0,0,0,0,0) and binding_count(e)==0 and cash_rows(e)==[] and requests(e)==[]

def test_interruption_rolls_back_request_binding_and_cash(bound_env):
    e=bound_env
    class Interrupted(BaseException):pass
    def interrupt(point):
        if point=='BEFORE_COMMIT':raise Interrupted()
    e['source'].checkpoint=interrupt
    with pytest.raises(Interrupted):process(e)
    assert counts(e)==(0,0,0,0,0,0) and requests(e)==[] and cash_rows(e)==[] and binding_count(e)==0
