import pytest
from reconciliation import reservation,fee_attribution,enrollment_preflight

def r(state='CANCELLED',filled=0,**kw):
    return reservation(10000,state,10,filled,position_flat=kw.get('flat',True),broker_reconciled=kw.get('broker',True),fees_final=kw.get('fees',True))

def test_unknown_retains_hold():assert r('UNKNOWN')['remaining_local_hold_cents']==10000

def test_working_retains_hold():assert r('WORKING')['candidate_local_release_cents']==0

def test_partial_retains_hold():assert r('PARTIAL',5)['candidate_local_release_cents']==0

def test_position_blocks_release():assert r(filled=5,flat=False)['candidate_local_release_cents']==0

def test_broker_blocks_release():assert r(broker=False)['candidate_local_release_cents']==0

def test_fees_block_release():assert r(fees=False)['candidate_local_release_cents']==0

def test_terminal_candidate_never_adds_broker_cash():
    x=r();assert x['candidate_local_release_cents']==10000 and x['broker_cash_addback_cents']==0 and not x['release_executed']

def test_filled_mismatch():
    with pytest.raises(ValueError):r('FILLED',5)

TRADES=[dict(trade_id='b',cycle_id='c',side='BUY',value_cents=10000),dict(trade_id='s',cycle_id='c',side='SELL',value_cents=12000)]
CHARGES=[dict(trade_id=x,component='total',amount_cents=50) for x in ('b','s')]

def test_attributed_net_cashflow():
    x=fee_attribution(TRADES,CHARGES,coverage_complete=True);assert x['cycles']['c']['net_cashflow_cents']==1900 and not x['net_pnl_certified']

def test_incomplete_fees_no_net():assert fee_attribution(TRADES,CHARGES[:1],coverage_complete=True)['cycles']['c']['net_cashflow_cents'] is None

def test_duplicate_charge_rejected():
    with pytest.raises(ValueError):fee_attribution(TRADES,CHARGES+CHARGES[:1],coverage_complete=True)

def test_empty_preparation_blocks_enrollment():
    x=enrollment_preflight(0,False,controller_paused=True);assert x['blockers'] and not x['live_enrollment_permitted']
