import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from consumer import Blocked
from support import build_partial,build_flat,add_exit,consume,END

@pytest.fixture
def env(tmp_path,monkeypatch):
    monkeypatch.setenv('HILEGA_PRODUCTION_WORKSPACE_MODE','SIMULATION_ONLY');monkeypatch.setenv('HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED','0')
    return build_flat(tmp_path/'fixture')

def test_terminal_flat_releases_exact_hold_and_preserves_pause(env):
    r=consume(env);state=env['consumer'].status()
    assert r['released_cents']==660000 and r['release_applied'] is True
    assert state['held_cents']==0 and state['settlements'][0]['remaining']==0
    assert len(state['receipts'])==1 and env['service'].status()['control']['mode']=='PAUSED'
    assert not env['service'].status()['control']['reconciled'] and not env['broker'].fills()

def test_duplicate_delivery_exactly_once(env):
    consume(env);r=consume(env)
    assert r['idempotent_replay'] and not r['release_applied']
    assert len(env['consumer'].status()['receipts'])==1
    assert len([e for e in env['service'].store.events() if e['type']=='OFFLINE_BROKER_OWNERSHIP_RELEASE_COMMITTED'])==1

def test_new_request_id_cannot_release_same_reservation_again(env):
    consume(env);r=consume(env,'other-release-id')
    assert not r['release_applied'] and env['consumer'].status()['held_cents']==0

def test_duplicate_receipt_is_not_new_current_proof(env):
    consume(env);r=consume(env,as_of='2026-10-26T10:30:00+05:30')
    assert r['current_proof_revalidated'] is False and not r['release_applied']

def test_stale_first_delivery_rejected(env):
    with pytest.raises(Exception):consume(env,as_of='2026-10-26T09:25:36+05:30')
    assert env['consumer'].status()['held_cents']==660000 and not env['consumer'].status()['receipts']

def test_partial_cancel_not_flat_cannot_release(env,tmp_path):
    p=build_partial(tmp_path/'partial')
    with pytest.raises(Blocked,match='POSITION_NOT_FLAT'):consume(p,as_of='2026-10-26T09:25:00+05:30')
    assert p['consumer'].status()['held_cents']==660000

def test_exit_pending_cannot_release(env,tmp_path):
    p=add_exit(build_partial(tmp_path/'pending'),filled=False)
    with pytest.raises(Blocked,match='POSITION_NOT_FLAT'):consume(p)
    assert p['consumer'].status()['held_cents']==660000

def test_changed_evidence_is_rejected(env):
    p=env['evidence']
    with p.tx() as d:
        row=json.loads(d.execute('SELECT data FROM verified_snapshot WHERE id=1').fetchone()[0]);row['trades'][0]['price']='101'
        d.execute('UPDATE verified_snapshot SET data=? WHERE id=1',(json.dumps(row),))
    with pytest.raises(Blocked,match='SOURCE_EVIDENCE_CHANGED'):consume(env)
    assert env['consumer'].status()['held_cents']==660000

def test_missing_receipt_rejected(env):
    with env['link'].adapter.store.tx() as d:d.execute('DELETE FROM receipts')
    with pytest.raises(Blocked,match='BOUND_DURABLE_RECEIPT'):consume(env)
    assert env['consumer'].status()['held_cents']==660000

def test_wrong_reservation_quantity_rejected(env):
    with env['service'].store.db() as d:
        h=json.loads(d.execute('SELECT data FROM sim_allocation_reservations').fetchone()[0]);h['quantity']=130
        d.execute('UPDATE sim_allocation_reservations SET data=?',(json.dumps(h),))
    with pytest.raises(Blocked,match='EXACT_HELD_CONTROLLER_LINK'):consume(env)
    assert env['consumer'].status()['held_cents']==660000

def test_interruption_inside_release_transaction_rolls_back_everything(env):
    class Stop(BaseException):pass
    def fail(point):
        if point=='AFTER_HOLD_UPDATE_BEFORE_RECEIPT':raise Stop()
    env['consumer'].checkpoint=fail
    with pytest.raises(Stop):consume(env)
    state=env['consumer'].status();assert state['held_cents']==660000 and not state['receipts'] and not state['settlements']
    env['consumer'].checkpoint=lambda p:None
    assert consume(env)['release_applied']

def test_ack_lost_after_commit_replays_receipt_without_second_release(env):
    class Stop(BaseException):pass
    def fail(point):
        if point=='AFTER_COMMIT_BEFORE_ACK':raise Stop()
    env['consumer'].checkpoint=fail
    with pytest.raises(Stop):consume(env)
    assert env['consumer'].status()['held_cents']==0
    env['consumer'].checkpoint=lambda p:None;r=consume(env)
    assert r['idempotent_replay'] and not r['release_applied'] and len(env['consumer'].status()['receipts'])==1

def test_proof_revalidation_does_not_modify_ownership_ledger(env):
    p=env['evidence'];before=p.ledger.report(as_of=END)
    consume(env);after=p.ledger.report(as_of=END)
    assert before==after

def test_concurrent_delivery_commits_once(env):
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda rid:consume(env,rid),['one','two']))
    assert sum(r['release_applied'] for r in results)==1 and len(env['consumer'].status()['receipts'])==1

def test_marker_required_for_every_consumption(env):
    (env['service'].store.path.parent/'ISOLATED_LINK_VALIDATION.json').unlink()
    with pytest.raises(Blocked,match='MARKED_ISOLATED'):consume(env)

def test_conflicting_replay_rejected(env):
    consume(env)
    with pytest.raises(Blocked,match='RELEASE_REQUEST_CONFLICT'):
        env['consumer'].consume(env['entry']['id'],snapshot_id='different',request_id='release1',as_of=END)

def test_restored_hold_after_receipt_requires_review(env):
    consume(env)
    with env['service'].store.db() as d:
        h=json.loads(d.execute('SELECT data FROM sim_allocation_reservations').fetchone()[0]);h['held_cents']=660000
        d.execute('UPDATE sim_allocation_reservations SET data=?',(json.dumps(h),))
    with pytest.raises(Blocked,match='HOLD_REGRESSION'):consume(env)
