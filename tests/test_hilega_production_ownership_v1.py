import copy,json
from pathlib import Path
import pytest
from market_lab.hilega_production_ownership_v1 import Ledger,ReviewRequired

DAY='2026-10-25'
def at(t):return DAY+'T'+t+':00+05:30'
def create(tmp_path,account='fixture-account-A'):
    l=Ledger(tmp_path/'ownership-fixture.sqlite',account)
    e=l.register_entry(signal_id='sig-A',signal_at=at('09:20'),intent_at=at('09:25'),direction='BEARISH',
        instrument='NSE_FO|DEMO_PE',product='I',quantity_=65,policy_id='BULLISH_GAP2_FULL_WMA2',strategy_version='fixture-version')
    l.bind_order(intent_id=e,order_id='B1',at=at('09:25'))
    return l,e

def buy(q=65,status='FILLED',pending=0):
    return dict(order_id='B1',instrument='NSE_FO|DEMO_PE',product='I',side='BUY',quantity=65,filled=q,pending=pending,status=status)
def trade(oid='B1',tid='T1',side='BUY',q=65,p='100',time='09:25'):
    return dict(order_id=oid,trade_id=tid,instrument='NSE_FO|DEMO_PE',product='I',side=side,quantity=q,price=p,filled_at=at(time))
def snap(q=65,orders=None,trades=None,time='09:26',sid='S1'):
    return dict(snapshot_id=sid,account_scope='fixture-account-A',evidence_mode='OFFLINE_FIXTURE',observed_at=at(time),complete=True,
        orders=orders if orders is not None else [buy()],trades=trades if trades is not None else [trade()],
        positions=[dict(instrument='NSE_FO|DEMO_PE',product='I',quantity=q)])
def run(l,s):return l.reconcile(s,as_of=s['observed_at'])
def assert_block(l,s,reason):
    r=run(l,s);assert r['status']=='REVIEW_REQUIRED' and r['reason']==reason
    assert not r['exposure_verified'] and not r['production_execution_enabled'] and not r['orders_sent']

def test_linked_signal_order_fill_position(tmp_path):
    l,e=create(tmp_path);r=run(l,snap())
    p=r['positions'][0]
    assert p['entry_id']==e and p['signal_id']=='sig-A' and p['direction']=='BEARISH'
    assert p['remaining']==65 and p['average_entry']=='100'
    assert r['fill_count']==1 and r['exposure_verified']
    report=l.report(as_of=at('09:26'));assert not report['entry_permission'] and not report['order_submission_supported']

def test_partial_entry_keeps_pending(tmp_path):
    l,e=create(tmp_path);r=run(l,snap(20,[buy(20,'PARTIAL',45)],[trade(q=20)]))
    assert r['positions'][0]['remaining']==20 and r['pending_orders']==['B1']
def test_cancelled_partial_entry_retains_filled_exposure(tmp_path):
    l,e=create(tmp_path);r=run(l,snap(20,[buy(20,'CANCELLED')],[trade(q=20)]))
    assert r['positions'][0]['remaining']==20 and r['pending_orders']==[]
def test_no_fill_cancel_has_no_fake_average(tmp_path):
    l,e=create(tmp_path);r=run(l,snap(0,[buy(0,'CANCELLED')],[]))
    assert r['positions'][0]['average_entry'] is None and r['positions'][0]['entry_filled']==0

def add_exit(l,e,*,qty=65,external=False,oid='E1',key='exit-A',time='09:27'):
    x=l.register_exit(entry_id=e,exit_key=key,intent_at=at(time),quantity_=qty,reason='EXTERNAL_APP_EXIT' if external else 'STRATEGY_EXIT',external=external,actor='fixture-operator' if external else None)
    l.bind_order(intent_id=x,order_id=oid,at=at(time));return x

def sell(oid='E1',qty=65,filled=65,pending=0,status='FILLED'):
    return dict(order_id=oid,instrument='NSE_FO|DEMO_PE',product='I',side='SELL',quantity=qty,filled=filled,pending=pending,status=status)
def closed_snap(q=0,qty=65):
    return snap(q,[buy(),sell(qty=qty,filled=qty)], [trade(),trade('E1','TE1','SELL',qty,'105','09:27')],time='09:28',sid='S2')
def test_explicit_external_exit_updates_quantity_once(tmp_path):
    l,e=create(tmp_path);run(l,snap());add_exit(l,e,external=True)
    s=closed_snap();r=run(l,s)
    assert r['positions'][0]['remaining']==0 and r['positions'][0]['gross_realised_premium_value']=='325'
    assert not r['positions'][0]['fees_included'] and not r['reversal_buy_allowed']
    assert run(l,s)['status']=='IDEMPOTENT_REPLAY'
    assert l.report(as_of=at('09:28'))['state']['fill_count']==2

def test_partial_external_exit_has_only_remaining_quantity(tmp_path):
    l,e=create(tmp_path);run(l,snap());add_exit(l,e,external=True,qty=20)
    r=run(l,closed_snap(45,20));assert r['positions'][0]['remaining']==45

def test_external_order_not_inferred_from_matching_instrument(tmp_path):
    l,e=create(tmp_path);run(l,snap())
    assert_block(l,closed_snap(),'UNMAPPED_ACTIVITY_ON_OWNED_INSTRUMENT')
def test_external_mapping_requires_actor(tmp_path):
    l,e=create(tmp_path)
    with pytest.raises(ReviewRequired):l.register_exit(entry_id=e,exit_key='x',intent_at=at('09:27'),quantity_=65,reason='EXTERNAL',external=True)
def test_missing_row_does_not_close_position(tmp_path):
    l,e=create(tmp_path);s=snap();s['positions']=[]
    assert_block(l,s,'MISSING_POSITION_IS_NOT_FLAT')
def test_position_change_without_fills_unknown(tmp_path):
    l,e=create(tmp_path);run(l,snap());s=snap(0,time='09:28',sid='S2')
    assert_block(l,s,'BROKER_POSITION_QUANTITY_MISMATCH')
def test_duplicate_identical_fill_not_double_counted(tmp_path):
    l,e=create(tmp_path);s=snap();s['trades'].append(copy.deepcopy(s['trades'][0]))
    assert run(l,s)['fill_count']==1

def test_duplicate_conflicting_fill_blocks(tmp_path):
    l,e=create(tmp_path);s=snap();t=copy.deepcopy(s['trades'][0]);t['price']='101';s['trades'].append(t)
    assert_block(l,s,'DUPLICATE_FILL_CONFLICT')
def test_fill_price_correction_requires_review(tmp_path):
    l,e=create(tmp_path);run(l,snap());s=snap(time='09:28',sid='S2');s['trades'][0]['price']='101'
    assert_block(l,s,'PREVIOUS_FILL_CHANGED')
def test_fill_evidence_disappearance_blocks(tmp_path):
    l,e=create(tmp_path);run(l,snap());s=snap(time='09:28',sid='S2');s['trades']=[]
    assert_block(l,s,'PREVIOUS_FILL_DISAPPEARED')
def test_no_fill_inferred_from_order_status(tmp_path):
    l,e=create(tmp_path);s=snap();s['trades']=[]
    assert_block(l,s,'ORDER_TRADE_FILL_TOTAL_MISMATCH')
def test_missing_owned_order_unknown(tmp_path):
    l,e=create(tmp_path);s=snap();s['orders']=[];s['trades']=[]
    assert_block(l,s,'OWNED_ORDER_EVIDENCE_MISSING')
def test_unknown_acceptance_never_allows_resubmit(tmp_path):
    l=Ledger(tmp_path/'fixture.sqlite','fixture-account-A')
    l.register_entry(signal_id='S',signal_at=at('09:20'),intent_at=at('09:25'),direction='BULLISH',instrument='NSE_FO|DEMO_CE',product='I',quantity_=65,policy_id='P',strategy_version='V')
    assert_block(l,snap(),'ORDER_ACCEPTANCE_UNKNOWN_NO_RESUBMISSION')
def test_mismatched_product_rejected(tmp_path):
    l,e=create(tmp_path);s=snap();s['orders'][0]['product']='D';s['trades'][0]['product']='D'
    assert_block(l,s,'BOUND_ORDER_IDENTITY_MISMATCH')
def test_fill_side_mismatch_rejected(tmp_path):
    l,e=create(tmp_path);s=snap();s['trades'][0]['side']='SELL'
    assert_block(l,s,'FILL_ORDER_IDENTITY_MISMATCH')
def test_oversell_blocked_atomically(tmp_path):
    l,e=create(tmp_path);run(l,snap(20,[buy(20,'CANCELLED')],[trade(q=20)]));add_exit(l,e,qty=65)
    s=snap(-45,[buy(20,'CANCELLED'),sell()], [trade(q=20),trade('E1','TE1','SELL',65,'105','09:27')],time='09:28',sid='S2')
    assert_block(l,s,'EXIT_FILLS_EXCEED_ENTRY_FILLS')
    with l.db() as d:assert len(l._load_fills(d))==1

def test_pending_exit_blocks_reversal_and_limits_quantity(tmp_path):
    l,e=create(tmp_path);run(l,snap());add_exit(l,e)
    s=snap(45,[buy(),sell(filled=20,pending=45,status='PARTIAL')],[trade(),trade('E1','TE1','SELL',20,'105','09:27')],time='09:28',sid='S2')
    r=run(l,s);assert r['pending_orders']==['E1'] and not r['reversal_buy_allowed']
def test_two_pending_exits_cannot_reserve_same_quantity(tmp_path):
    l,e=create(tmp_path);run(l,snap());add_exit(l,e,qty=40);add_exit(l,e,qty=40,oid='E2',key='exit-B')
    s=snap(65,[buy(),sell(qty=40,filled=0,pending=40,status='OPEN'),sell('E2',40,0,40,'OPEN')],[trade()],time='09:28',sid='S2')
    assert_block(l,s,'PENDING_EXITS_EXCEED_REMAINING')
def test_account_scopes_isolated(tmp_path):
    l,e=create(tmp_path);s=snap();s['account_scope']='other-account'
    assert_block(l,s,'ACCOUNT_SCOPE_MISMATCH')
    other=Ledger(l.path,'other-account');assert other.report(as_of=at('09:26'))['state']['status']=='NOT_RECONCILED'
def test_order_cannot_be_rebound(tmp_path):
    l,e=create(tmp_path);x=l.register_exit(entry_id=e,exit_key='x',intent_at=at('09:27'),quantity_=65,reason='X')
    with pytest.raises(ReviewRequired):l.bind_order(intent_id=x,order_id='B1',at=at('09:27'))
@pytest.mark.parametrize('mode',['LIVE_READ_ONLY','LIVE','SIMULATION_ONLY',None])
def test_fixture_only_gate(tmp_path,mode):
    l,e=create(tmp_path);s=snap();s['evidence_mode']=mode
    assert_block(l,s,'OFFLINE_FIXTURE_REQUIRED')
@pytest.mark.parametrize('delta',[-1,31])
def test_stale_or_future_snapshot_blocks(tmp_path,delta):
    from datetime import timedelta
    from market_lab.hilega_production_ownership_v1 import timestamp
    l,e=create(tmp_path);s=snap();when=(timestamp(s['observed_at'])+timedelta(seconds=delta)).isoformat()
    assert l.reconcile(s,as_of=when)['reason']=='SNAPSHOT_STALE_OR_FUTURE'
def test_report_staleness_hides_previous_position(tmp_path):
    l,e=create(tmp_path);run(l,snap());r=l.report(as_of=at('09:27'))
    assert r['state']['status']=='STALE' and 'positions' not in r['state']
def test_restart_preserves_fills_and_idempotency(tmp_path):
    l,e=create(tmp_path);run(l,snap());restarted=Ledger(l.path,l.account)
    assert run(restarted,snap())['status']=='IDEMPOTENT_REPLAY'
    assert restarted.report(as_of=at('09:26'))['state']['fill_count']==1

def test_incomplete_snapshot_blocks(tmp_path):
    l,e=create(tmp_path);s=snap();s['complete']=False;assert_block(l,s,'SNAPSHOT_INCOMPLETE')
def test_same_snapshot_id_changed_evidence_rejected(tmp_path):
    l,e=create(tmp_path);run(l,snap());s=snap();s['positions'][0]['quantity']=0
    assert_block(l,s,'SNAPSHOT_ID_REUSED_WITH_CHANGED_EVIDENCE')
def test_out_of_order_after_failure_still_blocked(tmp_path):
    l,e=create(tmp_path);run(l,snap(time='09:28'));bad=snap(time='09:29',sid='BAD');bad['positions']=[];run(l,bad)
    assert_block(l,snap(time='09:27',sid='OLD'),'OUT_OF_ORDER_SNAPSHOT')
def test_missing_price_never_creates_pnl(tmp_path):
    l,e=create(tmp_path);s=snap();s['trades'][0].pop('price');assert_block(l,s,'INVALID_FILL_PRICE')
def test_unowned_position_blocks(tmp_path):
    l,e=create(tmp_path);s=snap();s['positions'].append(dict(instrument='OTHER',product='I',quantity=1))
    assert_block(l,s,'UNOWNED_BROKER_EXPOSURE')
def test_duplicate_position_keys_rejected(tmp_path):
    l,e=create(tmp_path);s=snap();s['positions'].append(copy.deepcopy(s['positions'][0]));assert_block(l,s,'DUPLICATE_POSITION_EVIDENCE')
def test_failed_snapshot_commits_no_partial_fills(tmp_path):
    l,e=create(tmp_path);s=snap(0);run(l,s)
    with l.db() as d:assert l._load_fills(d)=={}
def test_repeat_entry_registration_is_idempotent(tmp_path):
    l,e=create(tmp_path);r=create(tmp_path)[1];assert r==e
    with l.db() as d:assert len(l._intents(d))==1

@pytest.mark.parametrize('value',[True,0,-1,1.5])
def test_invalid_fill_quantity_rejected(tmp_path,value):
    l,e=create(tmp_path);s=snap();s['trades'][0]['quantity']=value
    assert_block(l,s,'INVALID_QUANTITY')
@pytest.mark.parametrize('value',[True,'NaN',float('inf'),0,-1])
def test_invalid_fill_price_rejected(tmp_path,value):
    l,e=create(tmp_path);s=snap();s['trades'][0]['price']=value
    # JSON disallows infinity even before field validation; either path must block.
    r=run(l,s);assert r['status']=='REVIEW_REQUIRED' and not r['exposure_verified']
def test_numeric_price_representation_is_normalized(tmp_path):
    l,e=create(tmp_path);run(l,snap());s=snap(time='09:28',sid='S2');s['trades'][0]['price']=100.0
    assert run(l,s)['fill_count']==1

def test_same_order_id_different_account_is_not_same_ownership(tmp_path):
    a,e=create(tmp_path);run(a,snap());b,e2=create(tmp_path,'fixture-account-B')
    s=snap();s['account_scope']='fixture-account-B';assert run(b,s)['positions'][0]['entry_id']==e2
    assert e!=e2

def test_previous_day_open_order_cannot_disappear(tmp_path):
    l,e=create(tmp_path);run(l,snap(20,[buy(20,'PARTIAL',45)],[trade(q=20)]))
    s=snap(20,[],[],time='09:26',sid='NEXT');s['observed_at']='2026-10-26T09:26:00+05:30'
    assert_block(l,s,'PRIOR_SESSION_ORDER_OUTCOME_UNRESOLVED')

def test_previous_day_terminal_entry_can_carry_with_durable_fills(tmp_path):
    l,e=create(tmp_path);run(l,snap());s=snap(65,[],[],sid='NEXT')
    s['observed_at']='2026-10-26T09:26:00+05:30'
    r=run(l,s);assert r['positions'][0]['remaining']==65
    assert not r['reversal_buy_allowed']

def test_terminal_status_regression_blocks(tmp_path):
    l,e=create(tmp_path);run(l,snap());s=snap(time='09:28',sid='S2');s['orders'][0]['status']='OPEN'
    assert_block(l,s,'TERMINAL_ORDER_REGRESSION')

def test_cancelled_partial_status_can_gain_late_confirmed_fill(tmp_path):
    l,e=create(tmp_path);run(l,snap(20,[buy(20,'CANCELLED')],[trade(q=20)]))
    s=snap(65,[buy()],[trade(q=20),trade(tid='T2',q=45,time='09:27')],time='09:28',sid='S2')
    assert run(l,s)['positions'][0]['remaining']==65
