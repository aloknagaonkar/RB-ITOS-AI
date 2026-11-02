from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
import pytest
from readiness import Blocked,profile_capabilities,cash_preview,order_state_policy,reconcile_charge_totals,collect,milestone


def profile():return dict(status='success',data=dict(is_active=True,exchanges=['NFO'],products=['I'],order_types=['LIMIT']))


def fake():
    calls=[];now=datetime.now(timezone.utc)
    def get(name):calls.append(name);return profile() if name=='profile' else {'status':'success'}
    account=dict(status='READ_ONLY_CAPTURED',orders=[],trades=[],positions=[],diagnostics={'issues':[]},account_position_rows_complete=True)
    api=SimpleNamespace(matches=lambda *a:None,capture=lambda *a,**k:account,verify=lambda *a,**k:None,
        day=lambda t:t.date().isoformat(),sign=lambda *a:'synthetic-signature')
    obs=SimpleNamespace(sanitize=lambda *a:dict(status='PASS',cash_available_to_trade=1000,cash_margin_used=0))
    return SimpleNamespace(get=get),api,obs,calls,now


def test_unknown_outcome_never_permits_resubmission():
    r=order_state_policy('UNKNOWN',65,0);assert r['action']=='BLOCK_UNKNOWN_NO_RESUBMISSION' and r['automatic_resubmission'] is False


def test_cancelled_partial_holds_residual_for_review():
    r=order_state_policy('CANCELLED',65,20);assert r['remaining_quantity']==45 and r['action']=='MANUAL_RESIDUAL_REVIEW_REQUIRED'


def test_filled_status_with_partial_quantity_is_rejected():
    with pytest.raises(Blocked):order_state_policy('FILLED',65,20)


def test_cash_does_not_add_back_broker_usage_or_release_reservations():
    r=cash_preview('1000.01',10000);assert r['conservative_capacity_cents']==40000
    assert r['broker_cash_added_back_cents']==0 and r['reservation_release_permission'] is False


def test_boolean_cash_is_rejected():
    with pytest.raises(Blocked):cash_preview(True,0)


def test_charge_total_match_does_not_claim_fee_completeness():
    r=reconcile_charge_totals('23.60',{'brokerage':'20','gst':'3.60'})
    assert r['aggregate_total_verified'] and r['fees_complete'] is False and r['per_cycle_attribution_verified'] is False


def test_charge_total_mismatch_blocks():
    with pytest.raises(Blocked):reconcile_charge_totals('1',{'component':'2'})


def test_profile_capabilities_are_not_execution_permission():
    r=profile_capabilities(profile());assert r['capabilities_present'] and r['execution_permission'] is False


def test_successful_get_evidence_is_signed_and_has_no_key_or_token():
    client,api,obs,calls,now=fake();e,r=collect(client,{'scope':'synthetic'},api,obs,clock=lambda:now)
    assert e['signature']=='synthetic-signature' and r['broker_network_get_validated']
    assert calls==['profile','funds','funds','profile'];assert 'key' not in e and 'token' not in e


def test_profile_mismatch_stops_before_funds_or_account_capture():
    client,api,obs,calls,now=fake()
    def mismatch(*a):raise Blocked('PINNED_ACCOUNT_MISMATCH')
    api.matches=mismatch
    with pytest.raises(Blocked):collect(client,{'scope':'synthetic'},api,obs,clock=lambda:now)
    assert calls==['profile']


def test_slow_sweep_cannot_become_fresh_evidence():
    client,api,obs,calls,now=fake();times=iter([now,now+timedelta(seconds=31)])
    with pytest.raises(Blocked,match='SLOW'):collect(client,{'scope':'synthetic'},api,obs,clock=lambda:next(times))


def test_broker_get_capture_cannot_complete_group2():
    r=milestone({'broker_network_get_validated':True});assert r['group2_complete'] is False
    assert r['production_execution_enabled'] is False and len(r['tasks'])==6
