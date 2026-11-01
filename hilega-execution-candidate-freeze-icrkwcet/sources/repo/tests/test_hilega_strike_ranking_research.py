from datetime import datetime, timedelta
from types import SimpleNamespace
import pytest
from scripts.research_hilega_strike_ranking import compare_trade, incomplete_trade, summarize, validate_frozen

AT=datetime.fromisoformat('2026-10-14T12:00:00+05:30')

def fixture():
    trade=dict(direction='BULLISH', entry_time=AT.isoformat(), exit_time=(AT+timedelta(minutes=2)).isoformat(), entry_price=22500)
    frozen=dict(strategy_entry_time=trade['entry_time'], expiry='2026-10-19', nearest_expiry_verified=True,
                atm=22500, strike_interval=50, contracts=[dict(role=i, option_type='CE', expiry='2026-10-19',
                strike=22500+i*50,instrument_key=str(i),lot_size=65) for i in (-2,-1,0,1,2)])
    candles=[]
    for r in frozen['contracts']:
        for n in range(3):
            candles.append(SimpleNamespace(instrument_key=r['instrument_key'], side='CE', strike=r['strike'],
                expiry=frozen['expiry'], session_date='2026-10-14', timestamp=AT+timedelta(minutes=n),
                open=100+n,high=103+n,low=99+n,close=101+n,volume=100))
    session=SimpleNamespace(session_date='2026-10-14',expiry=frozen['expiry'],rows=candles)
    return trade,frozen,session


def compare(trade,frozen,session):
    return compare_trade(trade,session,lag_minutes=0,trade_index=1,frozen=frozen,
                         round_trip_cost_rupees=30,slippage_points_per_side=.5)


def test_missing_cache_trades_remain_in_denominator():
    t,f,s=fixture(); rows=compare(t,f,s)+incomplete_trade('2026-10-15',t,1,'MISSING_CACHE')
    summary=summarize(rows)
    assert all(r['expected_trades']==2 and r['coverage_pct']==50 for r in summary)


def test_common_five_cohort_excludes_trade_missing_any_role():
    t,f,s=fixture(); s.rows=[c for c in s.rows if c.instrument_key!='2']
    summary=summarize(compare(t,f,s))
    assert all(r['common_five_complete_trades']==0 for r in summary)
    assert sum(r['complete'] for r in summary)==4


def test_net_cost_scenario_and_adverse_movement():
    t,f,s=fixture(); row=compare(t,f,s)[0]
    assert row['gross_rupees']==130 and row['net_rupees']==35
    assert row['mae_points']==-1 and row['mfe_points']==4


def test_nearest_expiry_and_entry_boundary_must_match():
    t,f,s=fixture(); f['nearest_expiry_verified']=False
    with pytest.raises(ValueError,match='NEAREST'):validate_frozen(f,t,s.session_date)
    f['nearest_expiry_verified']=True; f['strategy_entry_time']='other'
    with pytest.raises(ValueError,match='ENTRY_TIME'):validate_frozen(f,t,s.session_date)
