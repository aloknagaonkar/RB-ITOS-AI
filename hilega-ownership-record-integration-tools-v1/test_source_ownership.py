"""VM-only actual Source + ownership record, exclusively in pytest temp databases."""
from copy import deepcopy
from datetime import timedelta
import json
import pytest
from test_hilega_application_preparation_v1 import env,process,append,counts
from test_hilega_atomic_disabled_binding_v1 import bound_env
from hilega_application_preparation_fixtures import PIN,T
from market_lab.hilega_execution_port_v1.adapter import Store,Adapter,FixtureTransport,encode
from market_lab.hilega_preparation_runtime_v1 import ownership_state as state
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import MODEL,LIVE,sign


@pytest.fixture(autouse=True)
def synthetic_scope(monkeypatch):
    monkeypatch.setitem(PIN,'scope','FIXTURE:APPLICATION-OWNERSHIP-RECORD')
    from market_lab.hilega_production_broker_observation_v1 import Client
    monkeypatch.setattr(Client,'get',lambda *a,**k:pytest.fail('No broker reads in tests'))


@pytest.fixture
def recorded_entry(bound_env,tmp_path,monkeypatch):
    e=bound_env;process(e)
    assert e['store'].path.resolve().parent==tmp_path.resolve()
    assert e['adapter_store'].path.resolve().parent==tmp_path.resolve()
    assert PIN['scope'].startswith('FIXTURE:')
    # This is the synthetic pytest adapter only. Never relabel a live account.
    with e['adapter_store'].tx() as db:
        db.execute('UPDATE meta SET data=? WHERE id=1',(
            encode(dict(scope=PIN['scope'],mode='OFFLINE_FIXTURE')),))
    fixture_store=Store(e['adapter_store'].path,PIN['scope'],'OFFLINE_FIXTURE')
    transport=FixtureTransport(fixture_store);adapter=Adapter(fixture_store,transport)
    request,=fixture_store.requests();adapter.submit(request['request_id'])
    request,=fixture_store.requests();q=request['draft']['body']['quantity']
    transport.fill(request['order_id'],q)
    order,=transport.orders();order.update(pending=0,placed_at=(T+timedelta(seconds=3)).isoformat())
    snapshot=dict(model=MODEL,evidence_mode=LIVE,account_scope=PIN['scope'],
        snapshot_id='synthetic-source-ownership',session_date=T.date().isoformat(),
        generated_at=(T+timedelta(seconds=5)).isoformat(),
        completed_at=(T+timedelta(seconds=6)).isoformat(),
        status='READ_ONLY_CAPTURED',account_identity_verified=True,
        profile_verified_before_and_after=True,account_position_rows_complete=True,
        source_atomic=False,position_fill_linkage_verified=False,live_pnl=None,
        production_execution_enabled=False,orders_sent=False,entry_permission=False,
        diagnostics={},orders=[order],positions=[dict(instrument=order['instrument'],product='I',quantity=q)],
        trades=[dict(order_id=order['order_id'],trade_id='synthetic-fill',instrument=order['instrument'],
            product='I',side='BUY',quantity=q,price='100',filled_at=(T+timedelta(seconds=4)).isoformat())])
    snapshot['signature']=sign(snapshot,PIN);e['clock'][0]=T+timedelta(seconds=7)
    result=state.record_entry_review(e['store'].path,fixture_store.path,snapshot,PIN,
        mode='OFFLINE_FIXTURE',clock=lambda:e['clock'][0])
    assert result['record_status']=='ENTRY_QUANTITY_RECONCILED'
    original=state.closed_exit_context
    monkeypatch.setattr(state,'closed_exit_context',lambda source,db,event,*,now,resources:
        original(source,db,event,now=now,pin=PIN,mode='OFFLINE_FIXTURE',resources=resources))
    e.update(fixture_store=fixture_store,snapshot=snapshot,quantity=q)
    return e


def exit_once(e):
    append(e['path'],['STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21'])
    e['source'].run_source_once(e['path'])
    with e['store'].db() as db:
        return json.loads(db.execute('SELECT data FROM preparation_exit_dispatch').fetchone()[0])


def test_actual_source_links_read_only_owned_quantity(recorded_entry):
    e=recorded_entry
    before=e['fixture_store'].requests()
    with e['store'].db() as db:
        cash=db.execute('SELECT data FROM preparation_cash_reservations').fetchone()[0]
    row=exit_once(e)
    assert row['entry_ownership_context']['reviewed_entry_quantity']==e['quantity']
    assert row['dispatch_status']=='REFUSED_CLOSED' and row['exit_quantity'] is None
    assert row['executable_request_created'] is False
    assert e['fixture_store'].requests()==before
    with e['store'].db() as db:
        assert db.execute('SELECT data FROM preparation_cash_reservations').fetchone()[0]==cash
    assert e['store'].control()['mode']=='PAUSED'
    assert counts(e)==(1,1,1,0,0,0)


def test_actual_source_rejects_stale_ownership_context(recorded_entry):
    e=recorded_entry;e['clock'][0]+=timedelta(seconds=31)
    row=exit_once(e)
    assert row['entry_ownership_context']['reviewed_entry_quantity'] is None
    assert row['entry_ownership_context']['reason']=='OWNERSHIP_STATE_STALE_OR_FUTURE'
    assert row['orders_sent'] is False


def test_actual_source_exit_rollback_keeps_ownership_and_hold(recorded_entry):
    e=recorded_entry
    class Interrupted(BaseException):pass
    def stop(point):
        if point=='BEFORE_CLOSED_EXIT_DISPATCH_COMMIT':raise Interrupted()
    e['source'].checkpoint=stop
    with pytest.raises(Interrupted):exit_once(e)
    with e['store'].db() as db:
        assert db.execute('SELECT COUNT(*) FROM preparation_cash_reservations').fetchone()[0]==1
        row=state.current_row(db,PIN,'OFFLINE_FIXTURE')
        assert row['reviewed_entry_quantity']==e['quantity']
    e['source'].checkpoint=lambda point:None
    e['source'].run_source_once(e['path'])
    with e['store'].db() as db:
        assert db.execute('SELECT COUNT(*) FROM preparation_exit_dispatch').fetchone()[0]==1
    assert len(e['fixture_store'].requests())==1
