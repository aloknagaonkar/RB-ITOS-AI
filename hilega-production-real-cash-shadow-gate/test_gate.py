from datetime import datetime,timedelta
from concurrent.futures import ThreadPoolExecutor
import copy
import pytest
from gate import ShadowBook,Blocked,verify_capture,cents
from market_lab.hilega_production_account_adapter_v1 import sign
from synthetic_evidence import AT,PIN,capture

@pytest.fixture
def book(tmp_path):return ShadowBook(tmp_path/'shadow.sqlite',PIN['scope'])
def preview(book,r=None,cost=None):return book.preview(r or capture(),PIN,as_of=AT,proposed_cost=cost)

def test_verified_empty_baseline_does_not_grant_trading(book):
    r=preview(book,cost='6600');assert r['half_cash_cap']=='50000.00' and r['shadow_plan_within_cap']
    assert r['entry_permission'] is False and r['production_execution_enabled'] is False
    assert r['debit_attribution']=='NOT_VALIDATED'

def test_hold_deducted_in_full_without_addback(book):
    book.reserve_shadow('p1','6600',capture(),PIN,as_of=AT);r=preview(book)
    assert r['full_local_holds']=='6600.00' and r['conservative_capacity']=='43400.00'
    assert r['broker_cash_addback']==r['assumed_reflected_overlap']=='0.00'
    assert r['potential_double_count_not_resolved']

def test_duplicate_plan_is_idempotent(book):
    for _ in range(2):book.reserve_shadow('p1','6600',capture(),PIN,as_of=AT)
    assert len(preview(book)['holds'])==1

def test_plan_conflict_rejected(book):
    book.reserve_shadow('p1','6600',capture(),PIN,as_of=AT)
    with pytest.raises(Blocked,match='PLAN_ID_CONFLICT'):book.reserve_shadow('p1','1',capture(),PIN,as_of=AT)

def test_unknown_retains_hold_and_blocks_more(book):
    book.reserve_shadow('p1','6600',capture(),PIN,as_of=AT);book.mark_unknown('p1')
    assert preview(book)['full_local_holds']=='6600.00'
    with pytest.raises(Blocked):book.reserve_shadow('p2','1',capture(),PIN,as_of=AT)
    with pytest.raises(Blocked):book.cancel_unsubmitted_shadow('p1')

def test_fresh_empty_account_does_not_release_unknown(book):
    book.reserve_shadow('p1','6600',capture(),PIN,as_of=AT);book.mark_unknown('p1')
    r=capture(snapshot_id='sample2',started_at='2026-10-26T09:25:01+05:30',completed_at='2026-10-26T09:25:01+05:30')
    result=book.preview(r,PIN,as_of=r['completed_at']);assert result['full_local_holds']=='6600.00'

def test_explicit_unsubmitted_shadow_cancel_is_only_release(book):
    book.reserve_shadow('p1','6600',capture(),PIN,as_of=AT)
    book.cancel_unsubmitted_shadow('p1');book.cancel_unsubmitted_shadow('p1')
    assert preview(book)['full_local_holds']=='0.00'

def test_restart_retains_hold(book):
    book.reserve_shadow('p1','6600',capture(),PIN,as_of=AT)
    assert preview(ShadowBook(book.path,PIN['scope']))['full_local_holds']=='6600.00'

def test_scope_cannot_change(book):
    with pytest.raises(Blocked,match='BOOK_ACCOUNT_SCOPE'):ShadowBook(book.path,'ANOTHER_SCOPE')

def test_tampered_signature_rejected(book):
    r=capture();r['funds_after']['cash_available_to_trade']='999999'
    with pytest.raises(Blocked,match='SIGNATURE'):preview(book,r)

def test_stale_capture_rejected(book):
    with pytest.raises(Blocked,match='STALE'):book.preview(capture(),PIN,as_of='2026-10-26T09:25:31+05:30')

def test_future_capture_rejected(book):
    with pytest.raises(Blocked,match='FUTURE'):book.preview(capture(),PIN,as_of='2026-10-26T09:24:59+05:30')

def test_wrong_session_rejected(book):
    with pytest.raises(Blocked):book.preview(capture(),PIN,as_of='2026-10-27T09:25:00+05:30')

def test_live_activity_requires_review(book):
    r=capture(orders=[dict(order_id='synthetic')]);result=preview(book,r,cost='1')
    assert not result['shadow_plan_within_cap']
    with pytest.raises(Blocked):book.reserve_shadow('p1','1',r,PIN,as_of=AT)

def test_nonzero_positions_require_review(book):
    assert not preview(book,capture(positions=[dict(quantity=65)]),cost='1')['shadow_plan_within_cap']

def test_zero_cash_blocks_shadow_proposal(book):
    r=preview(book,capture(cash='0'),cost='1')
    assert 'NO_CASH_CAPACITY' in r['reasons'] and not r['shadow_plan_within_cap']

def test_funds_drift_is_not_coherence(book):
    r=capture(funds_changed_during_capture=True)
    assert 'FUNDS_CHANGED_DURING_CAPTURE' in preview(book,r)['reasons']

def test_cap_does_not_round_up(book):
    assert preview(book,capture(cash='100.019'))['half_cash_cap']=='50.00'

def test_cost_rounds_up():assert cents('0.001',True)==1

@pytest.mark.parametrize('value',[True,'NaN','Infinity','-1',None])
def test_invalid_amount_rejected(value):
    with pytest.raises(Blocked):cents(value)

def test_reused_capture_id_rejected_even_with_valid_signature(book):
    preview(book)
    with pytest.raises(Blocked,match='CAPTURE_ID_REUSED'):preview(book,capture(cash='99999'))

def test_concurrent_reservations_share_half_cash_cap(book):
    def reserve(key):
        try:book.reserve_shadow(key,'30000',capture(),PIN,as_of=AT);return 'RESERVED'
        except Blocked:return 'BLOCKED'
    with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(reserve,['p1','p2']))
    assert sorted(result)==['BLOCKED','RESERVED'] and preview(book)['full_local_holds']=='30000.00'
