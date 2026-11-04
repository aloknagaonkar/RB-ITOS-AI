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


def test_observed_camelcase_zero_page_count_uses_exact_record_bound():
    from historical import observation
    v=response();v['metaData']=v.pop('meta_data');v['data'].append(dict(sample(),trade_id='t2'))
    v['metaData']['page'].update(total_records=2,total_pages=0)
    assert page(v,1,100)[1:]==(2,1,100)
    observed=observation(v)
    assert observed['declared_total_pages']==0 and observed['derived_total_pages']==1
    assert not observed['declared_page_count_matches_derived'] and not observed['broker_zero_page_count_semantics_confirmed']


def test_zero_declared_pages_cannot_bypass_page_limit():
    v=response();v['meta_data']['page'].update(total_records=501,total_pages=0)
    with pytest.raises(ValueError,match='DERIVED_PAGE_LIMIT'):page(v,1,100)


def test_positive_declared_page_conflict_is_rejected():
    v=response();v['meta_data']['page']['total_pages']=2
    with pytest.raises(ValueError,match='DECLARED_PAGE_COUNT_CONFLICT'):page(v,1,100)


def test_boolean_page_number_is_not_an_integer_identity():
    v=response();v['meta_data']['page']['page_number']=True
    with pytest.raises(ValueError,match='PAGE_IDENTITY_CHANGED'):page(v,1,100)
