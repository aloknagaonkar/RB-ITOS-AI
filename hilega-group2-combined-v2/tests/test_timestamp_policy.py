from copy import deepcopy
from timestamp_policy import inspect_book,parse

def book(order='2026-11-02 13:58:06',trade='2026-11-02 19:28:06'):
    return dict(status='success',data=[dict(order_id='synthetic',order_timestamp=order)]),dict(status='success',data=[dict(order_id='synthetic',exchange_timestamp=trade)])
def inspect(order=None,trade=None,at='2026-11-02T13:58:33+00:00'):
    a,b=book() if order is None else book(order,trade)
    return inspect_book(a,b,observed_at=at)
def test_exact_reported_pattern_stays_blocked_after_clock_catches_up():assert inspect()['review_required']
def test_pattern_blocked_before_future_time():assert inspect(at='2026-11-02T13:55:34+00:00')['review_required']
def test_explicit_offsets_describe_same_instant():assert not inspect('2026-11-02T13:58:06+05:30','2026-11-02T08:28:06+00:00')['review_required']
def test_ordinary_naive_pair_not_flagged():assert not inspect('2026-11-02 13:58:06','2026-11-02 13:58:07')['review_required']
def test_inputs_not_changed_or_relabelled():
    a,b=book();before=deepcopy((a,b));inspect_book(a,b,observed_at='2026-11-02T14:00:00+00:00');assert (a,b)==before
def test_real_future_remains_visible():assert inspect('2026-11-02T14:00:00+00:00','2026-11-02T14:01:00+00:00')['examples'][0]['future_trade']
def test_legacy_month_format_matches_ist():assert parse('02-Nov-2026 13:58:06')[0].isoformat()=='2026-11-02T08:28:06+00:00'
def test_invalid_timestamp_is_not_guessed():
    a,b=book(trade='unknown');r=inspect_book(a,b,observed_at='2026-11-02T14:00:00+00:00');assert r['parse_issues']==1

def normalizer_book(trade_time):
    a=dict(status='success',data=[dict(order_id='synthetic',instrument_token='NSE_FO|1',product='I',transaction_type='BUY',quantity=1,filled_quantity=1,pending_quantity=0,status='complete',order_timestamp='2026-11-02T08:28:06+00:00')])
    b=dict(status='success',data=[dict(order_id='synthetic',trade_id='synthetic-trade',instrument_token='NSE_FO|1',product='I',transaction_type='BUY',quantity=1,average_price=100,exchange_timestamp=trade_time)])
    return a,b,dict(status='success',data=[])

def test_candidate_normalizer_blocks_reported_pattern_even_after_time_passes():
    import pytest
    from market_lab import hilega_production_account_adapter_v1 as api
    a,b,p=normalizer_book('2026-11-02 19:28:06');a['data'][0]['order_timestamp']='2026-11-02 13:58:06'
    with pytest.raises(api.AdapterBlocked,match='BROKER_TIMESTAMP_SEMANTICS_UNVERIFIED'):api.normalise(a,b,p,observed_at='2026-11-02T14:00:00+00:00')

def test_candidate_normalizer_preserves_genuine_future_trade_rejection():
    import pytest
    from market_lab import hilega_production_account_adapter_v1 as api
    a,b,p=normalizer_book('2026-11-02T14:01:00+00:00')
    with pytest.raises(api.AdapterBlocked,match='TRADE_TIME_OUTSIDE_ORDER_SESSION'):api.normalise(a,b,p,observed_at='2026-11-02T14:00:00+00:00')
