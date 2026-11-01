"""Offline tests only; all network calls are forbidden or explicitly stubbed."""
import copy,json,os
from datetime import datetime,timedelta,timezone
import pytest
from market_lab import hilega_production_account_adapter_v1 as a

STAMP='2026-10-25T09:22:00+05:30'
def at(seconds=0):return datetime.fromisoformat(STAMP)+timedelta(seconds=seconds)
def profile(uid='TESTACCOUNT_A'):return dict(status='success',data=dict(broker='UPSTOX',user_id=uid,is_active=True,user_name='DO_NOT_STORE',email='DO_NOT_STORE'))
def response(rows):return dict(status='success',data=rows)
def order(status='complete',filled=65,pending=0):
    return dict(order_id='ORDER1',instrument_token='NSE_FO|TEST',product='I',transaction_type='BUY',quantity=65,
                filled_quantity=filled,pending_quantity=pending,status=status,order_timestamp='2026-10-25 09:20:00',placed_by='DO_NOT_STORE')
def trade(**kw):
    r=dict(order_id='ORDER1',trade_id='TRADE1',instrument_token='NSE_FO|TEST',product='I',transaction_type='BUY',quantity=65,
        average_price=100.5,exchange_timestamp='25-Oct-2026 09:21:00',order_timestamp='2026-10-25 09:20:00');r.update(kw);return r

def normal(o=None,t=None,p=None):return a.normalise(response(o or []),response(t or []),response(p or []),observed_at=STAMP)
@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(a.Client,'get',lambda *args:pytest.fail('NETWORK_FORBIDDEN_IN_TEST'))
@pytest.fixture
def pin(tmp_path):return a.enroll(tmp_path/'private/account.json',profile(),'TESTACCOUNT_A',at=STAMP)
def captured(monkeypatch,pin,orders=None,trades=None,positions=None,after=None,clock=None):
    profiles=iter([profile(),after or profile()]);data=dict(orders=response(orders or []),trades=response(trades or []),positions=response(positions or []))
    calls=[]
    def get(self,n):calls.append(n);return next(profiles) if n=='profile' else data[n]
    monkeypatch.setattr(a.Client,'get',get)
    times=iter([at(),at(1)])
    r=a.capture(a.Client('FAKE_TEST_TOKEN'),pin,clock=clock or (lambda:next(times)))
    return r,calls

def test_pin_private_and_has_no_raw_profile(tmp_path):
    p=tmp_path/'private/account.json';pin=a.enroll(p,profile(),'TESTACCOUNT_A',at=STAMP)
    assert os.stat(p).st_mode&0o777==0o600 and os.stat(p.parent).st_mode&0o777==0o700
    assert 'TESTACCOUNT_A' not in p.read_text() and 'DO_NOT_STORE' not in p.read_text()
    assert a.read_pin(p)==pin

def test_wrong_expected_account_cannot_enroll(tmp_path):
    p=tmp_path/'private/account.json'
    with pytest.raises(a.AdapterBlocked,match='EXPECTED_ACCOUNT_DOES_NOT_MATCH_PROFILE'):a.enroll(p,profile(),'WRONG',at=STAMP)
    assert not p.exists()
def test_enrollment_never_overwrites_existing_pin(tmp_path):
    p=tmp_path/'private/account.json';a.enroll(p,profile(),'TESTACCOUNT_A',at=STAMP);before=p.read_bytes()
    with pytest.raises(a.AdapterBlocked,match='ACCOUNT_PIN_EXISTS_NO_OVERWRITE'):a.enroll(p,profile(),'TESTACCOUNT_A',at=STAMP)
    assert before==p.read_bytes()
def test_pin_group_readable_rejected(tmp_path):
    p=tmp_path/'private/account.json';a.enroll(p,profile(),'TESTACCOUNT_A',at=STAMP);p.chmod(0o640)
    with pytest.raises(a.AdapterBlocked):a.read_pin(p)
def test_pin_directory_public_rejected(tmp_path):
    p=tmp_path/'private/account.json';a.enroll(p,profile(),'TESTACCOUNT_A',at=STAMP);p.parent.chmod(0o755)
    with pytest.raises(a.AdapterBlocked):a.read_pin(p)
def test_pin_symlink_rejected(tmp_path):
    p=tmp_path/'private/account.json';a.enroll(p,profile(),'TESTACCOUNT_A',at=STAMP)
    link=p.parent/'link.json';link.symlink_to(p)
    with pytest.raises(a.AdapterBlocked):a.read_pin(link)
def test_profile_broker_must_match(pin):
    raw=profile();raw['data']['broker']='OTHER'
    with pytest.raises(a.AdapterBlocked):a.matches(raw,pin)
def test_account_mismatch_rejected(pin):
    with pytest.raises(a.AdapterBlocked,match='BROKER_ACCOUNT_MISMATCH'):a.matches(profile('TESTACCOUNT_B'),pin)
def test_inactive_account_rejected(pin):
    raw=profile();raw['data']['is_active']=False
    with pytest.raises(a.AdapterBlocked):a.matches(raw,pin)
def test_missing_identity_rejected(pin):
    raw=profile();raw['data'].pop('user_id')
    with pytest.raises(a.AdapterBlocked):a.matches(raw,pin)

def test_pinned_capture_checks_identity_twice(monkeypatch,pin):
    r,calls=captured(monkeypatch,pin)
    assert calls==['profile','orders','trades','positions','profile']
    assert r['account_identity_verified'] and not r['source_atomic'] and r['evidence_mode']==a.LIVE
    assert not r['entry_permission'] and not r['production_execution_enabled']
    assert 'TESTACCOUNT_A' not in json.dumps(r) and 'DO_NOT_STORE' not in json.dumps(r)
    assert a.verify(r,pin,as_of=at(2).isoformat())['status']=='IDENTITY_AND_READ_ONLY_EVIDENCE_VERIFIED'
def test_initial_mismatch_stops_before_account_data(monkeypatch,pin):
    calls=[]
    def get(self,n):calls.append(n);return profile('OTHERACCOUNT')
    monkeypatch.setattr(a.Client,'get',get);r=a.capture(a.Client('FAKE'),pin,clock=lambda:at())
    assert calls==['profile'] and r['status']=='BLOCKED' and r['orders'] is None

def test_end_profile_change_invalidates_entire_capture(monkeypatch,pin):
    r,c=captured(monkeypatch,pin,after=profile('TESTACCOUNT_B'))
    assert r['reason']=='BROKER_ACCOUNT_MISMATCH' and r['positions'] is None

def test_access_rejection_has_safe_error_no_response_body(monkeypatch,pin):
    monkeypatch.setattr(a.Client,'get',lambda *x:dict(status='FAIL',error='HTTP_403',provider_code='CLOUDFLARE_1010',message='SECRET'))
    r=a.capture(a.Client('FAKE'),pin,clock=lambda:at())
    assert r['reason']=='PROFILE_HTTP_403_CLOUDFLARE_1010' and 'SECRET' not in json.dumps(r)
def test_failure_after_profile_stops_remaining_requests(monkeypatch,pin):
    calls=[]
    def get(self,n):calls.append(n);return profile() if n=='profile' else dict(status='FAIL',error='HTTP_401')
    monkeypatch.setattr(a.Client,'get',get);r=a.capture(a.Client('FAKE'),pin,clock=lambda:at())
    assert calls==['profile','orders'] and r['positions'] is None

def test_sweep_over_30_seconds_is_not_fresh(monkeypatch,pin):
    times=iter([at(),at(31)]);r,c=captured(monkeypatch,pin,clock=lambda:next(times))
    assert r['reason']=='CAPTURE_WINDOW_TOO_LONG_OR_SESSION_CHANGED'
def test_midnight_sweep_rejected(monkeypatch,pin):
    times=iter([datetime.fromisoformat('2026-10-25T23:59:59+05:30'),datetime.fromisoformat('2026-10-26T00:00:01+05:30')])
    r,c=captured(monkeypatch,pin,clock=lambda:next(times))
    assert r['reason']=='CAPTURE_WINDOW_TOO_LONG_OR_SESSION_CHANGED'

@pytest.mark.parametrize('status',sorted(a.ACTIVE))
def test_documented_nonterminal_states_remain_active(status):
    r=normal([order(status,0,65)])
    assert r['orders'][0]['status']=='OPEN' and r['orders'][0]['source_status']==status

def test_partial_fill_uses_trade_quantity_not_order_quantity():
    r=normal([order('open',20,45)],[trade(quantity=20)])
    assert r['orders'][0]['status']=='PARTIAL' and r['trades'][0]['quantity']==20
    assert not r['diagnostics']['strategy_ownership_verified']
def test_cancelled_partial_order_still_contains_fills():
    r=normal([order('cancelled',20)],[trade(quantity=20)])
    assert r['orders'][0]['status']=='CANCELLED' and r['trades'][0]['quantity']==20

def test_unknown_status_never_defaults_to_complete():
    with pytest.raises(a.AdapterBlocked):normal([order('unrecognized')],[trade()])
def test_complete_quantity_mismatch_rejected():
    with pytest.raises(a.AdapterBlocked):normal([order('complete',20)],[trade(quantity=20)])
def test_order_status_does_not_create_missing_fill():
    r=normal([order()]);assert 'ORDER_TRADE_FILL_TOTAL_MISMATCH' in r['diagnostics']['issues']
    assert r['trades']==[]
def test_duplicate_identical_trade_deduplicates():
    r=normal([order()],[trade(),trade()]);assert len(r['trades'])==1

def test_conflicting_trade_duplicate_rejected():
    with pytest.raises(a.AdapterBlocked):normal([order()],[trade(),trade(average_price=101)])
def test_fill_without_order_rejected():
    with pytest.raises(a.AdapterBlocked):normal(t=[trade()])
def test_product_mismatch_rejected():
    with pytest.raises(a.AdapterBlocked):normal([order()],[trade(product='D')])
@pytest.mark.parametrize('price',[None,True,'NaN',0,-1,float('inf')])
def test_invalid_prices_cannot_become_fill_values(price):
    with pytest.raises(a.AdapterBlocked):normal([order()],[trade(average_price=price)])
def test_duplicate_positions_rejected():
    p=dict(instrument_token='NSE_FO|TEST',product='I',quantity=65)
    with pytest.raises(a.AdapterBlocked):normal(p=[p,p])
def test_unowned_exposure_reports_review():
    r=normal(p=[dict(instrument_token='NSE_FO|TEST',product='I',quantity=-65)])
    assert 'BROKER_EXPOSURE_NOT_MAPPED_TO_STRATEGY' in r['diagnostics']['issues']
def test_empty_positions_not_relabelled_as_verified_flat_strategy():
    r=normal();assert r['diagnostics']['status']=='EMPTY_ACCOUNT_SNAPSHOT_ONLY'
    assert not r['position_fill_linkage_verified'] and not r['diagnostics']['strategy_ownership_verified']
@pytest.mark.parametrize('value',['2026-10-25 09:21:00','25-Oct-2026 09:21:00','2026-10-25T03:51:00Z'])
def test_documented_exchange_timestamps_convert_to_ist(value):
    assert a.broker_time(value).astimezone(a.IST).isoformat()=='2026-10-25T09:21:00+05:30'
def test_missing_exchange_timestamp_not_replaced_by_order_time():
    t=trade();t.pop('exchange_timestamp')
    with pytest.raises(a.AdapterBlocked):normal([order()],[t])
def test_wrong_day_trade_rejected():
    with pytest.raises(a.AdapterBlocked):normal([order()],[trade(exchange_timestamp='2026-10-24 09:21:00')])
def test_future_trade_rejected():
    with pytest.raises(a.AdapterBlocked):normal([order()],[trade(exchange_timestamp='2026-10-25 09:23:00')])

def test_snapshot_tampering_rejected(monkeypatch,pin):
    r,c=captured(monkeypatch,pin);r['positions'].append(dict(quantity=100))
    with pytest.raises(a.AdapterBlocked,match='SNAPSHOT_SIGNATURE_INVALID'):a.verify(r,pin,as_of=at(2).isoformat())
def test_fixture_mode_cannot_become_live_evidence(monkeypatch,pin):
    r,c=captured(monkeypatch,pin);r['evidence_mode']='OFFLINE_FIXTURE';r.pop('signature');r['signature']=a.sign(r,pin)
    with pytest.raises(a.AdapterBlocked,match='LIVE_PINNED_EVIDENCE_REQUIRED'):a.verify(r,pin,as_of=at(2).isoformat())
@pytest.mark.parametrize('seconds',[-1,31])
def test_expired_or_future_signed_snapshot_rejected(monkeypatch,pin,seconds):
    r,c=captured(monkeypatch,pin)
    with pytest.raises(a.AdapterBlocked):a.verify(r,pin,as_of=at(seconds).isoformat())
def test_other_pin_cannot_verify_snapshot(monkeypatch,pin,tmp_path):
    r,c=captured(monkeypatch,pin);other=a.enroll(tmp_path/'other/account.json',profile(),'TESTACCOUNT_A',at=STAMP)
    with pytest.raises(a.AdapterBlocked):a.verify(r,other,as_of=at(2).isoformat())
def test_saved_snapshot_does_not_expose_pin_secret(monkeypatch,pin,tmp_path):
    r,c=captured(monkeypatch,pin);p=tmp_path/'snapshot.json';a.save_capture(r,p,tmp_path/'private/account.json')
    assert pin['key'] not in p.read_text() and os.stat(p).st_mode&0o777==0o600

def test_snapshot_cannot_overwrite_pin(monkeypatch,pin,tmp_path):
    r,c=captured(monkeypatch,pin);p=tmp_path/'private/account.json'
    with pytest.raises(a.AdapterBlocked):a.save_capture(r,p,p)
def test_offline_ledger_still_rejects_live_adapter_evidence(monkeypatch,pin,tmp_path):
    from market_lab.hilega_production_ownership_v1 import Ledger
    r,c=captured(monkeypatch,pin);l=Ledger(tmp_path/'fixture-only.sqlite',pin['scope'])
    result=l.reconcile(r,as_of=at(2).isoformat())
    assert result['reason']=='OFFLINE_FIXTURE_REQUIRED'

def test_date_only_timestamp_is_not_a_trade_time():
    with pytest.raises(a.AdapterBlocked):a.broker_time('2026-10-25')
def test_pin_works_after_token_renewal_for_same_account(monkeypatch,pin):
    monkeypatch.setattr(a.Client,'get',lambda self,n:profile() if n=='profile' else response([]))
    times=iter([at(),at(1)])
    r=a.capture(a.Client('NEW_FAKE_TOKEN'),pin,clock=lambda:next(times))
    assert r['account_scope']==pin['scope'] and r['account_identity_verified']
def test_changed_account_is_never_reenrolled_automatically(monkeypatch,pin,tmp_path):
    monkeypatch.setattr(a.Client,'get',lambda *x:profile('OTHERACCOUNT'))
    r=a.capture(a.Client('FAKE'),pin,clock=lambda:at())
    assert r['status']=='BLOCKED' and pin['scope']==a.account_scope(pin['key'],'TESTACCOUNT_A')
def test_signature_rejects_permission_escalation(monkeypatch,pin):
    r,c=captured(monkeypatch,pin);r['entry_permission']=True;r.pop('signature');r['signature']=a.sign(r,pin)
    with pytest.raises(a.AdapterBlocked,match='UNEXPECTED_EXECUTION_PERMISSION'):a.verify(r,pin,as_of=at(2).isoformat())
def test_invalid_pin_is_not_silently_replaced(tmp_path):
    p=tmp_path/'private/account.json';p.parent.mkdir(mode=0o700);p.write_text('{}');p.chmod(0o600)
    with pytest.raises(a.AdapterBlocked):a.read_pin(p)
    assert p.read_text()=='{}'
def test_terminal_pending_quantity_requires_review():
    with pytest.raises(a.AdapterBlocked,match='TERMINAL_ORDER_PENDING_QUANTITY_REQUIRES_REVIEW'):normal([order('cancelled',20,45)],[trade(quantity=20)])
def test_duplicate_order_ids_rejected():
    with pytest.raises(a.AdapterBlocked,match='DUPLICATE_ORDER_ID'):normal([order(),order()],[trade()])
