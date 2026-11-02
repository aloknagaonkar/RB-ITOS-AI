from copy import deepcopy
import pytest
from compare import compare_trade,delta,price_equal
from read_client import get

def row(at='2026-11-02 19:28:06'):
    return dict(order_id='synthetic-order',trade_id='synthetic-trade',instrument_token='NSE_FO|1',product='I',transaction_type='BUY',quantity=1,average_price=100,exchange_timestamp=at,order_timestamp='2026-11-02 13:58:06')
def test_matches_fill_without_exposing_ids():
    x=compare_trade(row(),[row()],[]);assert x['unique_fill_match'] and 'order_id' not in x and not x['execution_permission']
def test_duplicate_is_not_selected():assert compare_trade(row(),[row(),row()],[])['match_count']==2 and not compare_trade(row(),[row(),row()],[])['unique_fill_match']
def test_quantity_difference_blocks_match():
    b=row();b['quantity']=2;assert not compare_trade(row(),[b],[])['unique_fill_match']
def test_exact_offset_is_reported_not_corrected():
    a=row();b=row('2026-11-02 13:58:06');before=deepcopy((a,b));r=compare_trade(a,[b],[])
    assert r['day_minus_per_order_exchange_time']==dict(seconds=19800.0,basis='NAIVE_WALL_CLOCK_ONLY') and (a,b)==before and not r['timezone_contract_confirmed']
def test_mixed_offsets_not_guessed():assert delta('2026-11-02T13:58:06+00:00','2026-11-02 13:58:06')['seconds'] is None
def test_explicit_offsets_compare_same_instant():assert delta('2026-11-02T13:58:06+05:30','2026-11-02T08:28:06+00:00')['seconds']==0
def test_nonfinite_price_rejected():assert not price_equal('NaN','NaN')
def test_no_mutation_endpoint_can_be_requested():
    with pytest.raises(ValueError,match='AUDIT_ENDPOINT_NOT_ALLOWED'):get(object(),'place','synthetic')
