import sys,copy
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from analysis import funds,compare,Blocked

def raw(cash=100000):
    return dict(status='success',data=dict(available_to_trade=dict(cash_available_to_trade=dict(total=cash,
        margin_used=dict(total=0,premium_present=0),cash=dict(opening_balance=100000,added_today=0,withdrawn_today=0,amount_from_stock_sale=0,unpaid_charges=0)))))
def snap(cash=100000,at='2026-10-26T09:25:00+05:30'):
    return dict(status='READ_ONLY_CAPTURED',account_scope='PINNED_FIXTURE',session_date=at[:10],started_at=at,completed_at=at,
        funds_before=funds(raw(cash)),funds_after=funds(raw(cash)),orders=[],trades=[],positions=[])
def later(cash=100000):return snap(cash,'2026-10-26T09:25:10+05:30')
def test_baseline_never_claims_attribution():
    r=compare(None,snap());assert r['status']=='BASELINE_ONLY' and r['debit_attribution']=='NOT_VALIDATED'
def test_no_activity_does_not_prove_mapping():
    r=compare(snap(),later());assert r['status']=='NO_OBSERVED_CHANGE' and not r['entry_permission']
def test_cash_drop_is_observation_not_order_debit():
    r=compare(snap(),later(90000));assert r['cash_deltas']['cash_available_to_trade']=='-10000'
    assert r['debit_attribution']=='NOT_VALIDATED' and r['status']=='ACTIVITY_OBSERVED_ATTRIBUTION_PENDING'
def test_cash_margin_not_added_back():
    v=raw(90000);v['data']['available_to_trade']['cash_available_to_trade']['margin_used']['total']=10000
    f=funds(v);assert f['cash_available_to_trade']=='90000' and f['half_cash_preview']=='45000.00'
def test_optional_breakdown_stays_unknown():
    f=funds(dict(status='success',data=dict(available_to_trade=dict(cash_available_to_trade=dict(total=100,margin_used=dict(total=0))))))
    assert f['premium_present'] is None and f['cash_activity']['added_today'] is None
@pytest.mark.parametrize('v',[True,'NaN','Infinity',-1])
def test_invalid_cash_rejected(v):
    with pytest.raises(Blocked):funds(raw(v))
def test_missing_cash_is_not_zero():
    with pytest.raises(Blocked):funds(dict(status='success',data={}))
def test_new_session_baseline_only():
    r=compare(snap(),snap(at='2026-10-27T09:25:00+05:30'));assert r['status']=='NEW_SESSION_BASELINE_ONLY'
def test_account_scope_mismatch():
    s=later();s['account_scope']='OTHER';assert compare(snap(),s)['status']=='ACCOUNT_SCOPE_MISMATCH'
def test_overlap_rejected():assert compare(snap(),snap())['status']=='OVERLAPPING_OR_NONMONOTONIC_CAPTURES'
def test_error_not_replaced_with_old_evidence():assert compare(snap(),dict(status='BLOCKED'))['status']=='EVIDENCE_UNAVAILABLE'
def test_missing_fill_flags_regression():
    p=snap();p['trades']=[dict(order_id='o1',trade_id='t1',quantity=65,price='100')]
    r=compare(p,later());assert r['status']=='BROKER_EVIDENCE_REGRESSION_REVIEW_REQUIRED' and r['missing_fill_count']==1

def test_new_fill_and_cash_change_never_prove_causality():
    s=later(93500);s['trades']=[dict(order_id='o1',trade_id='t1',quantity=65,price='100')]
    r=compare(snap(),s);assert r['new_fill_count']==1 and r['debit_attribution']=='NOT_VALIDATED'
def test_within_sweep_cash_change_marked():
    s=later(99000);s['funds_before']=funds(raw(100000));assert compare(snap(),s)['funds_changed_during_capture']
def test_deposit_activity_is_confounded_not_trade_profit():
    s=later(110000);s['funds_after']['cash_activity']['added_today']='10000'
    r=compare(snap(),s);assert 'added_today' in r['cash_activity_fields_changed'] and r['debit_attribution']=='NOT_VALIDATED'
def test_corrected_trade_is_review_required():
    p=snap();p['trades']=[dict(order_id='o1',trade_id='t1',quantity=65,price='100')]
    s=later();s['trades']=[dict(order_id='o1',trade_id='t1',quantity=65,price='101')]
    assert compare(p,s)['corrected_fill_count']==1
