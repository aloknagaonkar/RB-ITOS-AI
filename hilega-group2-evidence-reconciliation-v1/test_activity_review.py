import copy
import pytest
from activity_review import review


def rows():
    identity=dict(order_id='o', instrument_token='NSE_FO|1', transaction_type='BUY', product='I', exchange='NFO')
    return ([dict(identity, status='complete', filled_quantity=2)],
            [dict(identity, trade_id='t', quantity=2, average_price=100)], [dict(quantity=0)])


def test_consistent_snapshot_does_not_certify_finance_or_ownership():
    r=review(*rows())
    assert r['order_fill_quantity_and_identity_consistent']
    assert not any(r[k] for k in ['strategy_ownership_verified','actual_fees_reconciled','net_pnl_certified','local_reservation_release_permitted','execution_permission'])


@pytest.mark.parametrize('kind,expected', [
    ('quantity','ORDER_FILL_QUANTITY_MISMATCH'), ('identity','ORDER_TRADE_IDENTITY_MISMATCH'),
    ('duplicate','DUPLICATE_TRADE_ID'), ('unmatched','UNMATCHED_TRADE_ORDER'),
    ('price','INVALID_TRADE_PRICE'), ('position','POSITION_QUANTITY_SCHEMA_INCOMPLETE')])
def test_inconsistent_snapshot_blocks(kind, expected):
    o,t,p=rows()
    if kind=='quantity': t[0]['quantity']=1
    if kind=='identity': t[0]['product']='D'
    if kind=='duplicate': t.append(copy.deepcopy(t[0]))
    if kind=='unmatched': t[0]['order_id']='other'
    if kind=='price': t[0]['average_price']='NaN'
    if kind=='position': p[0]['quantity']=False
    r=review(o,t,p)
    assert expected in r['structural_issues'] and not r['order_fill_quantity_and_identity_consistent']


def test_empty_day_does_not_clear_timestamp_contract_or_financial_readiness():
    r=review([],[],[])
    assert r['order_rows']==r['trade_rows']==0
    assert not r['execution_permission'] and not r['actual_fees_reconciled']
