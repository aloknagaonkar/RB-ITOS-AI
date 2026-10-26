"""Synthetic signed normalized captures; not live broker execution evidence."""
import copy
from datetime import datetime,timedelta,timezone
import pytest
from review import Journal,compare
from market_lab.hilega_production_account_adapter_v1 import MODEL,LIVE,sign,AdapterBlocked

T=datetime(2026,10,26,4,0,tzinfo=timezone.utc)
PIN={'key':'a'*64,'scope':'UPSTOX:'+'b'*64}

def report(n,*,buy=0,sell=0,qty=None,order_status='FILLED'):
    at=T+timedelta(seconds=n*2)
    orders=[];trades=[]
    for oid,side,q in [('b','BUY',buy),('s','SELL',sell)]:
        if not q:continue
        orders.append(dict(order_id=oid,instrument='NSE_FO|fixture',product='I',side=side,
                           quantity=q,filled=q,pending=0,status=order_status,placed_at=T.isoformat()))
        trades.append(dict(order_id=oid,trade_id=oid+'t',instrument='NSE_FO|fixture',product='I',side=side,
                           quantity=q,price='100',filled_at=T.isoformat()))
    data=dict(model=MODEL,evidence_mode=LIVE,generated_at=at.isoformat(),completed_at=at.isoformat(),
              session_date='2026-10-26',snapshot_id=str(n),account_scope=PIN['scope'],
              status='READ_ONLY_CAPTURED',account_identity_verified=True,production_execution_enabled=False,
              entry_permission=False,orders_sent=False,orders=orders,trades=trades,
              positions=[dict(instrument='NSE_FO|fixture',product='I',quantity=buy-sell if qty is None else qty)],
              account_position_rows_complete=True,diagnostics={})
    data['signature']=sign(data,PIN)
    return data

def resign(r):
    r.pop('signature',None);r['signature']=sign(r,PIN);return r

def record(j,r,late=0):
    return j.record(r,as_of=(datetime.fromisoformat(r['completed_at'])+timedelta(seconds=late)).isoformat())

@pytest.fixture
def journal(tmp_path):return Journal(tmp_path/'review',PIN)

def test_empty_baseline(journal):
    r=record(journal,report(1));assert r['comparison']=='BASELINE_ONLY';assert not r['entry_permission']

def test_stable(journal):
    record(journal,report(1));assert record(journal,report(2))['comparison']=='NO_OBSERVED_CHANGE'

@pytest.mark.parametrize('sell,kind',[(20,'ACCOUNT_LONG_REDUCED_UNATTRIBUTED'),(65,'ACCOUNT_LONG_CLOSED_UNATTRIBUTED')])
def test_sell_reductions(journal,sell,kind):
    record(journal,report(1,buy=65));r=record(journal,report(2,buy=65,sell=sell))
    assert r['changes'][0]['classification']==kind
    assert not r['strategy_ownership_verified'];assert not r['reservation_release_permission']

def test_missing_sell_not_close(journal):
    record(journal,report(1,buy=65));r=record(journal,report(2,buy=65,qty=0))
    assert r['reason']=='POSITION_DELTA_NOT_EXPLAINED_BY_NEW_FILLS'

def test_signature(journal):
    r=report(1);r['positions'][0]['quantity']=65
    assert record(journal,r)['reason']=='SNAPSHOT_SIGNATURE_INVALID'

def test_stale(journal):assert record(journal,report(1),31)['reason']=='SNAPSHOT_STALE_OR_FUTURE'

def test_duplicate(journal):
    r=report(1);record(journal,r)
    assert record(journal,r)['reason']=='DUPLICATE_CAPTURE_NOT_NEW_EVIDENCE'

def test_conflicting_id(journal):
    record(journal,report(1));r=report(2);r['snapshot_id']='1'
    assert record(journal,resign(r))['reason']=='SNAPSHOT_ID_CONFLICT'

def test_fill_regression(journal):
    record(journal,report(1,buy=65))
    r=report(2,buy=20)
    r['orders'][0].update(quantity=65,pending=45,status='PARTIAL')
    r=resign(r)
    assert record(journal,r)['reason']=='ORDER_FILL_REGRESSION'

def test_missing_previous_order(journal):
    record(journal,report(1,buy=65));assert record(journal,report(2))['reason']=='PREVIOUS_ORDER_MISSING'

def test_changed_fill(journal):
    record(journal,report(1,buy=65));r=report(2,buy=65);r['trades'][0]['price']='101'
    assert record(journal,resign(r))['reason']=='PREVIOUS_FILL_MISSING_OR_CHANGED'

def test_fill_order_mismatch(journal):
    r=report(1,buy=65);r['trades'][0]['quantity']=20
    assert record(journal,resign(r))['reason']=='ORDER_TRADE_FILL_TOTAL_MISMATCH'

def test_restart_preserves_history(journal):
    record(journal,report(1,buy=65));new=Journal(journal.directory,PIN)
    assert record(new,report(2,buy=65,sell=65))['changes'][0]['after']==0

def test_failure_does_not_replace_baseline(journal):
    record(journal,report(1,buy=65));record(journal,report(2,buy=65,qty=0))
    r=record(journal,report(3,buy=65,sell=65));assert r['status']=='READ_ONLY_REVIEWED'

def test_scope(journal):
    with pytest.raises(AdapterBlocked):Journal(journal.directory,dict(PIN,scope='UPSTOX:'+'c'*64))

def test_no_overlapping_sweep(journal):
    record(journal,report(2));assert record(journal,report(1))['reason']=='CAPTURE_OVERLAP_OR_OUT_OF_ORDER'

def test_missing_position_with_sell(journal):
    record(journal,report(1,buy=65));r=report(2,buy=65,sell=65);r['positions']=[]
    assert record(journal,resign(r))['changes'][0]['after']==0

def test_missing_position_without_sell(journal):
    record(journal,report(1,buy=65));r=report(2,buy=65);r['positions']=[]
    assert record(journal,resign(r))['status']=='REVIEW_REQUIRED'

def test_new_session_requires_baseline(journal):
    record(journal,report(1));r=report(2)
    for k in ('generated_at','completed_at'):r[k]=(datetime.fromisoformat(r[k])+timedelta(days=1)).isoformat()
    r['session_date']='2026-10-27'
    assert record(journal,resign(r))['reason']=='NEW_SESSION_REQUIRES_NEW_REVIEW_DIRECTORY'

def test_no_live_authority(journal):
    r=record(journal,report(1))
    for k in ('orders_sent','production_execution_enabled','application_ledger_updated','reservation_release_permission','strategy_ownership_verified'):
        assert r[k] is False


def test_ack_without_fill_is_not_exposure(journal):
    r=report(1)
    r['orders']=[dict(order_id='pending',instrument='NSE_FO|fixture',product='I',side='BUY',quantity=65,filled=0,pending=65,status='OPEN',placed_at=T.isoformat())]
    result=record(journal,resign(r))
    assert result['new_fill_count']==0
    assert result['changes']==[]

def test_cross_account(journal):
    r=report(1);r['account_scope']='UPSTOX:'+'c'*64
    assert record(journal,resign(r))['reason']=='SNAPSHOT_ACCOUNT_SCOPE_MISMATCH'

def test_false_complete_order(journal):
    r=report(1,buy=20);r['orders'][0]['quantity']=65
    assert record(journal,resign(r))['reason']=='INVALID_FILLED_ORDER'

def test_mixed_activity_not_manual_exit_claim(journal):
    record(journal,report(1,buy=65))
    r=report(2,buy=65,sell=65)
    r['orders'].append(dict(order_id='b2',instrument='NSE_FO|fixture',product='I',side='BUY',quantity=20,filled=20,pending=0,status='FILLED',placed_at=T.isoformat()))
    r['trades'].append(dict(order_id='b2',trade_id='b2t',instrument='NSE_FO|fixture',product='I',side='BUY',quantity=20,price='101',filled_at=T.isoformat()))
    r['positions'][0]['quantity']=20
    assert record(journal,resign(r))['changes'][0]['classification']=='ACCOUNT_ACTIVITY_UNATTRIBUTED'
