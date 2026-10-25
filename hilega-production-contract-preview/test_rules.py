import sys,copy
from pathlib import Path
from datetime import datetime,timedelta,date,timezone
from decimal import Decimal
import pytest
sys.path.insert(0,str(Path(__file__).parent))
import rules as r
AT=datetime(2026,10,26,5,0,tzinfo=timezone.utc)
def contracts():
    return [dict(underlying_key=r.UNDERLYING,segment='NSE_FO',exchange='NSE',instrument_type=side,
        expiry='2026-10-27',strike_price=strike,instrument_key='NSE_FO|'+side+str(strike),trading_symbol='fixture',
        lot_size=65,minimum_lot=65,freeze_quantity=1800,tick_size=5)
        for side in ('CE','PE') for strike in range(22800,23251,50)]
def mapping(offsets=None,lots=1):return r.select(contracts(),23000,offsets or [0],lots,AT.date())
def q(key):
    return dict(instrument_token=key,last_price=100,timestamp=int(AT.timestamp()*1000),
        last_trade_time=int(AT.timestamp()*1000),volume=1000,
        depth=dict(buy=[dict(price=99,quantity=650)],sell=[dict(price=100,quantity=650)]))
def preview(cash=100000,market='NORMAL_OPEN',offsets=None):
    m=mapping(offsets);qs={x['instrument_key']:q(x['instrument_key']) for x in m['contracts']}
    return r.assess(m,qs,cash,market,AT,100)
def test_initial_one_lot_atm_both_direction_previews_separate():
    m=mapping();assert len(m['contracts'])==2 and all(x['quantity']==65 for x in m['contracts'])
    out=preview();assert all(x['estimated_cost']=='6600.00' for x in out['baskets'])
    assert out['production_execution_enabled'] is False and out['entry_permission'] is False
@pytest.mark.parametrize('offsets',[[0,0],[-3],[3],[],[True]])
def test_invalid_offsets(offsets):
    with pytest.raises(r.Blocked):r.select(contracts(),23000,offsets,1,AT.date())
def test_five_strikes_one_total_directional_cap():
    out=preview(cash=50000,offsets=[-2,-1,0,1,2])
    assert all(x['estimated_cost']=='33000.00' and not x['preview_checks_passed'] for x in out['baskets'])
def test_lot_size_from_broker_not_hardcoded():
    cs=contracts()
    for x in cs:x.update(lot_size=75,minimum_lot=75)
    assert all(x['quantity']==150 for x in r.select(cs,23000,[0],2,AT.date())['contracts'])
def test_duplicate_contract_rejected():
    cs=contracts();cs.append(copy.deepcopy(next(x for x in cs if x['strike_price']==23000)))
    with pytest.raises(r.Blocked):r.select(cs,23000,[0],1,AT.date())
def test_missing_offset_contract_not_silently_skipped():
    cs=[x for x in contracts() if not (x['strike_price']==23050 and x['instrument_type']=='PE')]
    with pytest.raises(r.Blocked):r.select(cs,23000,[1],1,AT.date())
def test_expired_contract_never_used():
    with pytest.raises(r.Blocked):r.select(contracts(),23000,[0],1,date(2026,10,28))
def test_atm_tie_higher_strike():assert r.select(contracts(),23025,[0],1,AT.date())['atm']=='23050'
def test_stale_quote():
    v=q('k');v['timestamp']=int((AT-timedelta(seconds=11)).timestamp()*1000)
    assert 'QUOTE_STALE_OR_FUTURE' in r.quality(v,65,AT,10,Decimal(2))['reasons']
def test_future_quote():
    v=q('k');v['timestamp']=int((AT+timedelta(seconds=1)).timestamp()*1000)
    assert 'QUOTE_STALE_OR_FUTURE' in r.quality(v,65,AT,10,Decimal(2))['reasons']
def test_fresh_response_old_trade_not_trade_ready():
    v=q('k');v['last_trade_time']=int((AT-timedelta(seconds=61)).timestamp()*1000)
    assert 'LAST_TRADE_STALE_OR_FUTURE' in r.quality(v,65,AT,10,Decimal(2))['reasons']
def test_insufficient_ask_depth():
    v=q('k');v['depth']['sell'][0]['quantity']=10
    assert 'BEST_ASK_DEPTH_BELOW_QUANTITY' in r.quality(v,65,AT,10,Decimal(2))['reasons']
def test_wide_spread():
    v=q('k');v['depth']['buy'][0]['price']=80
    assert 'SPREAD_ABOVE_PREVIEW_LIMIT' in r.quality(v,65,AT,10,Decimal(2))['reasons']
def test_crossed_book():
    v=q('k');v['depth']['buy'][0]['price']=101
    assert 'CROSSED_BOOK' in r.quality(v,65,AT,10,Decimal(2))['reasons']
def test_missing_depth_is_not_zero_cost():
    m=mapping();qs={x['instrument_key']:q(x['instrument_key']) for x in m['contracts']}
    for v in qs.values():v['depth']={}
    out=r.assess(m,qs,100000,'NORMAL_OPEN',AT,100)
    assert all(x['estimated_cost'] is None and not x['preview_checks_passed'] for x in out['baskets'])
def test_closed_market_never_passes():assert all(not x['preview_checks_passed'] for x in preview(market='CLOSED')['baskets'])
def test_funds_cap_is_maximum_not_spend_target():
    out=preview(cash='200000.01');assert out['half_cash_cap']=='100000.00'
    assert all(x['estimated_cost']=='6600.00' for x in out['baskets'])
@pytest.mark.parametrize('value',[True,'NaN','Infinity',-1])
def test_invalid_money(value):
    with pytest.raises(r.Blocked):r.number(value)
def test_quote_identity_must_match():
    with pytest.raises(r.Blocked):r.quote_map({'symbol':q('wrong')},['expected'])
def test_freeze_limit_blocks():
    with pytest.raises(r.Blocked):mapping(lots=100)
