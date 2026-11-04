from copy import deepcopy
import pytest
from historical import page,corroborate


def sample():
    return dict(segment='FO',trade_date='2026-11-02',trade_id='t1',exchange='NFO',transaction_type='BUY',quantity=65,price=100)
def old():return dict(trade_id='t1',exchange='NFO',transaction_type='BUY',quantity=65,average_price=100)
def response():return dict(status='success',data=[sample()],meta_data=dict(page=dict(page_number=1,page_size=100,total_records=1,total_pages=1)))


def test_historical_match_does_not_certify_timezone_or_ownership():
    v=corroborate([sample()],[old()],'2026-11-02')
    assert v['matching_trade_id_exchange_side_quantity_price_rows']==1 and not v['execution_timestamp_contract_verified'] and not v['strategy_ownership_verified']

def test_duplicate_trade_identity_is_ambiguous():
    assert corroborate([sample(),sample()],[old()],'2026-11-02')['ambiguous_matches']==1

def test_wrong_session_cannot_corroborate():
    row=sample();row['trade_date']='2026-11-03'
    v=corroborate([row],[old()],'2026-11-02');assert v['unmatched_prior_rows']==1 and v['out_of_scope_or_invalid_rows']==1

def test_price_or_quantity_conflict_blocks_match():
    row=sample();row['quantity']=64
    v=corroborate([row],[old()],'2026-11-02');assert v['conflicting_matches']==1 and v['matching_trade_id_exchange_side_quantity_price_rows']==0

def test_documented_meta_data_and_conflicting_alias():
    v=response();assert page(v,1,100)[1:]==(1,1,100)
    v['metadata']=deepcopy(v['meta_data']);v['metadata']['page']['total_records']=2
    with pytest.raises(ValueError,match='METADATA_REQUIRED'):page(v,1,100)

def test_excessive_or_wrong_pagination_is_rejected():
    v=response();v['meta_data']['page']['total_pages']=6
    with pytest.raises(ValueError,match='TOTALS_REQUIRED'):page(v,1,100)
