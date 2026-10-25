import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import datetime,timedelta
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from ledger import Ledger,Blocked,cost
DAY='2026-10-26';AT=DAY+'T09:25:00+05:30'
def legs(offsets=(0,),ask='100',lots=1):
    return [dict(instrument='FIXTURE|CE'+str(x),side='CE',offset=x,ask=ask,buffer='100',lot_size=65,lots=lots,quantity=65*lots) for x in offsets]
@pytest.fixture
def ledger(tmp_path):
    l=Ledger(tmp_path/'allocation.sqlite','FIXTURE_ACCOUNT')
    l.snapshot('funds1',cash='100000',observed_at=AT,as_of=AT,session_date=DAY)
    return l

def reserve(l,key='r1',signal='s1',plan=None,at=AT,snapshot='funds1',day=DAY):
    return l.reserve(key,signal_id=signal,snapshot_id=snapshot,legs=plan or legs(),as_of=at,session_date=day)
def evidence(l,state,eid=None,at=AT,proof=False):
    return l.evidence(eid or state,'r1',state=state,as_of=at,terminal_no_exposure=proof)
def test_single_lot_and_half_cash_cap(ledger):
    row=reserve(ledger);assert row['held_cents']==660000
    assert ledger.status()['held_total']=='6600.00' and ledger.status()['entry_permission'] is False

def test_basket_total_not_per_leg_limit(ledger):
    with pytest.raises(Blocked):reserve(ledger,plan=legs((-2,-1,0,1,2),ask='200'))
    assert ledger.status()['held_total']=='0.00'
def test_concurrent_requests_cannot_double_spend(ledger):
    barrier=Barrier(2)
    def work(n):
        barrier.wait()
        try:return reserve(ledger,'r'+str(n),'s'+str(n),legs((-2,-1,0,1,2)))['state']
        except Blocked as exc:return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(work,[1,2]))
    assert sorted(results)==['HALF_CASH_CAP_EXCEEDED','RESERVED']
    assert ledger.status()['held_total']=='33000.00'
def test_reservation_retry_idempotent(ledger):
    a=reserve(ledger);b=reserve(ledger)
    assert b['idempotent_replay'] and b['held_cents']==a['held_cents'] and len(ledger.status()['reservations'])==1

def test_same_id_different_plan_rejected(ledger):
    reserve(ledger)
    with pytest.raises(Blocked):reserve(ledger,plan=legs(ask='101'))
def test_same_signal_different_request_rejected(ledger):
    reserve(ledger)
    with pytest.raises(Blocked):reserve(ledger,'r2')
def test_restart_preserves_holds(ledger):
    reserve(ledger);again=Ledger(ledger.path,'FIXTURE_ACCOUNT')
    assert again.status()['held_total']=='6600.00'
def test_wrong_account_rejected(ledger):
    with pytest.raises(Blocked):Ledger(ledger.path,'ANOTHER_ACCOUNT')
def test_unknown_holds_and_blocks_new_entries(ledger):
    reserve(ledger);evidence(ledger,'UNKNOWN')
    with pytest.raises(Blocked,match='UNKNOWN_ORDER_OUTCOME'):reserve(ledger,'r2','s2')
    assert ledger.status()['held_total']=='6600.00'
@pytest.mark.parametrize('state',['SUBMITTED','PARTIAL','FILLED'])
def test_fills_never_release_reservation(ledger,state):
    reserve(ledger);evidence(ledger,'SUBMITTED')
    if state!='SUBMITTED':evidence(ledger,state)
    assert ledger.status()['held_total']=='6600.00'
def test_no_auto_expiry(ledger):
    reserve(ledger)
    nextday='2026-10-27T09:25:00+05:30'
    ledger.snapshot('funds2',cash='10000',observed_at=nextday,as_of=nextday,session_date='2026-10-27')
    with pytest.raises(Blocked):reserve(ledger,'r2','s2',at=nextday,snapshot='funds2',day='2026-10-27')
    assert ledger.status()['held_total']=='6600.00'
def test_release_requires_explicit_terminal_no_exposure(ledger):
    reserve(ledger)
    with pytest.raises(Blocked):evidence(ledger,'RELEASED')
    assert ledger.status()['held_total']=='6600.00'
def test_verified_fixture_cancel_releases_once(ledger):
    reserve(ledger);evidence(ledger,'RELEASED',proof=True)
    assert evidence(ledger,'RELEASED',proof=True)['idempotent_replay']
    assert ledger.status()['held_total']=='0.00'
def test_partial_cancel_keeps_hold_until_flat_proof(ledger):
    reserve(ledger);evidence(ledger,'SUBMITTED');evidence(ledger,'PARTIAL')
    with pytest.raises(Blocked):evidence(ledger,'RELEASED')
    evidence(ledger,'RELEASED',eid='flat',proof=True)
    assert ledger.status()['held_total']=='0.00'
def test_evidence_conflict_rejected(ledger):
    reserve(ledger);evidence(ledger,'SUBMITTED',eid='e1')
    with pytest.raises(Blocked):evidence(ledger,'UNKNOWN',eid='e1')
def test_released_cannot_reopen(ledger):
    reserve(ledger);evidence(ledger,'RELEASED',proof=True)
    with pytest.raises(Blocked):evidence(ledger,'SUBMITTED')
def test_evidence_time_regression(ledger):
    reserve(ledger);evidence(ledger,'SUBMITTED',at=DAY+'T09:25:01+05:30')
    with pytest.raises(Blocked):evidence(ledger,'PARTIAL')
def test_stale_funds_cannot_reserve(ledger):
    with pytest.raises(Blocked):reserve(ledger,at=DAY+'T09:25:31+05:30')
def test_latest_snapshot_required(ledger):
    ledger.snapshot('funds2',cash='50000',observed_at=AT,as_of=AT,session_date=DAY)
    with pytest.raises(Blocked):reserve(ledger)
def test_snapshot_id_conflict(ledger):
    with pytest.raises(Blocked):ledger.snapshot('funds1',cash='99999',observed_at=AT,as_of=AT,session_date=DAY)
def test_same_snapshot_retry(ledger):
    ledger.snapshot('funds1',cash='100000',observed_at=AT,as_of=AT,session_date=DAY)
    assert reserve(ledger)['state']=='RESERVED'
def test_budget_decrease_does_not_erase_existing_hold(ledger):
    reserve(ledger,plan=legs((-2,-1,0,1,2)))
    ledger.snapshot('funds2',cash='50000',observed_at=AT,as_of=AT,session_date=DAY)
    with pytest.raises(Blocked):reserve(ledger,'r2','s2',snapshot='funds2')
    assert ledger.status()['held_total']=='33000.00'
def test_round_up_cost_floor_cap(ledger):
    assert cost(legs(ask='100.00001'))==660001
@pytest.mark.parametrize('amount',['NaN','Infinity',True,-1])
def test_invalid_cash(ledger,amount):
    with pytest.raises(Blocked):ledger.snapshot('bad',cash=amount,observed_at=AT,as_of=AT,session_date=DAY)
def test_ce_pe_not_one_basket(ledger):
    plan=legs((0,1));plan[1]['side']='PE'
    with pytest.raises(Blocked):reserve(ledger,plan=plan)
def test_wrong_quantity(ledger):
    plan=legs();plan[0]['quantity']=1
    with pytest.raises(Blocked):reserve(ledger,plan=plan)
def test_duplicate_offsets(ledger):
    plan=legs((0,1));plan[1]['offset']=0
    with pytest.raises(Blocked):reserve(ledger,plan=plan)
def test_state_regression(ledger):
    reserve(ledger);evidence(ledger,'SUBMITTED');evidence(ledger,'FILLED')
    with pytest.raises(Blocked):evidence(ledger,'PARTIAL')
