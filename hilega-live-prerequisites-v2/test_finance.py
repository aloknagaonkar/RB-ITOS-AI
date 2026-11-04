import pytest
from finance import scope, review


def charges():
    return dict(status='success',data=dict(charges_breakdown=dict(total=10,brokerage=5,
        taxes=dict(gst=1,stt=1,stamp_duty=1),charges=dict(transaction=1,clearing=0,ipft=0,others=0,sebi_turnover=1,demat_transaction=0))))


def test_april_financial_year_boundary():
    assert scope('2026-03-31')['financial_year']=='2526'
    assert scope('2026-04-01')['financial_year']=='2627'
    assert scope('2026-11-02')['from_date']=='02-11-2026'


def test_balanced_aggregate_does_not_authorize_release():
    r=review(charges(),[dict(trade_type='OPT',quantity=1,buy_amount=10,sell_amount=12)],1)
    assert r['aggregate_component_arithmetic_matches'] and r['pagination_count_matches']
    assert not any(r[k] for k in ['actual_fees_reconciled','reservation_release_permitted','net_pnl_certified','strategy_ownership_verified'])


def test_null_is_unknown_not_zero():
    c=charges();c['data']['charges_breakdown']['charges']['ipft']=None
    r=review(c,[],0)
    assert r['missing_or_null_components']==['charges.ipft'] and not r['aggregate_component_arithmetic_matches']


def test_total_mismatch():
    c=charges();c['data']['charges_breakdown']['total']=11
    assert not review(c,[],0)['aggregate_component_arithmetic_matches']


def test_missing_page_not_complete():
    assert not review(charges(),[],1)['pagination_count_matches']


@pytest.mark.parametrize('value',[True, -1, 'NaN'])
def test_invalid_component(value):
    c=charges();c['data']['charges_breakdown']['brokerage']=value
    with pytest.raises(ValueError): review(c,[],0)
