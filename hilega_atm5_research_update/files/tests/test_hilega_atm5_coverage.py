from datetime import datetime, timedelta
from types import SimpleNamespace
import pytest
from scripts.research_hilega_atm5_coverage import atm_for, build_index, check_trade, summarize
from scripts.research_hilega_strike_ranking import incomplete_trade, roles_for, validate_frozen

AT=datetime.fromisoformat('2026-08-03T10:00:00+05:30')
DAY='2026-08-03'


def fixture(side='CE'):
    trade=dict(direction='BULLISH' if side=='CE' else 'BEARISH',entry_price=22500,
               entry_time=AT.isoformat(),exit_time=(AT+timedelta(minutes=2)).isoformat())
    rows=[]
    for role in range(-5,6):
        for n in range(3):
            rows.append(SimpleNamespace(session_date=DAY,expiry='2026-08-04',side=side,strike=22500+role*50,
                instrument_key=side+str(role),timestamp=AT+timedelta(minutes=n),underlying='NSE_INDEX|Nifty 50',
                open=100,high=102,low=99,close=101,volume=100,open_interest=500))
    s=SimpleNamespace(session_date=DAY,expiry='2026-08-04',strike_interval=50,rows=rows,source_path='fixture')
    return trade,s


@pytest.mark.parametrize('side',['CE','PE'])
def test_exact_eleven_paths_at_confirmed_entry(side):
    trade,session=fixture(side)
    rows=check_trade(trade,DAY,1,build_index([session],DAY),lag_minutes=0)
    assert len(rows)==11 and all(r['path_status']=='EXACT_CACHE_PATH_AVAILABLE' for r in rows)
    assert all(r['nearest_expiry_verified'] is False and r['lot_size_verified'] is False for r in rows)
    assert summarize(rows)[0]['all_roles_complete_trades']==1


def test_entry_atm_shift_exposes_missing_outer_strike():
    trade,s=fixture();trade['entry_price']=22560
    rows=check_trade(trade,DAY,1,build_index([s],DAY),lag_minutes=0)
    assert rows[-1]['strike']==22800 and rows[-1]['issue']=='EXACT_STRIKE_CONTRACT_MISSING'
    assert summarize(rows)[0]['all_roles_complete_trades']==0


def test_missing_minute_is_retained_in_coverage():
    trade,s=fixture();s.rows=[r for r in s.rows if not (r.instrument_key=='CE-5' and r.timestamp==AT+timedelta(minutes=1))]
    rows=check_trade(trade,DAY,1,build_index([s],DAY),lag_minutes=0)
    assert rows[0]['missing_minute_count']==1 and rows[0]['issue']=='MISSING_EXACT_OPTION_MINUTES'
    assert summarize(rows)[0]['exact_cached_paths']==10


def test_identical_duplicates_merge_but_conflicting_prices_block():
    trade,s=fixture();copy=SimpleNamespace(**vars(s.rows[0]));s.rows.append(copy)
    rows=check_trade(trade,DAY,1,build_index([s],DAY),lag_minutes=0)
    assert rows[0]['path_status']=='EXACT_CACHE_PATH_AVAILABLE'
    copy.open=99.5
    rows=check_trade(trade,DAY,1,build_index([s],DAY),lag_minutes=0)
    assert rows[0]['issue']=='CONFLICTING_OPTION_MINUTES'


def test_ambiguous_contract_not_selected_and_missing_day_denominator():
    trade,s=fixture();copy=SimpleNamespace(**vars(s.rows[0]));copy.instrument_key='other';s.rows.append(copy)
    rows=check_trade(trade,DAY,1,build_index([s],DAY),lag_minutes=0)
    assert rows[0]['issue']=='AMBIGUOUS_CONTRACT_IDENTITY'
    rows+=check_trade(trade,DAY,2,build_index([],DAY),lag_minutes=0)
    summary=summarize(rows)[0]
    assert summary['expected_trades']==2 and summary['expected_contract_paths']==22
    assert summary['exact_cached_paths']==10


def test_atm_tie_chooses_lower_and_wider_strict_manifest_requires_eleven():
    assert atm_for(22525)==22500
    assert roles_for(5)==tuple(range(-5,6))
    trade,s=fixture()
    assert len(incomplete_trade(DAY,trade,1,'NO_CACHE',wings=5))==11
    frozen=dict(strategy_entry_time=trade['entry_time'],expiry='2026-08-04',nearest_expiry_verified=True,
                atm=22500,strike_interval=50,contracts=[dict(role=i,option_type='CE',expiry='2026-08-04',
                strike=22500+i*50,instrument_key=str(i),lot_size=65) for i in range(-5,6)])
    assert len(validate_frozen(frozen,trade,DAY,wings=5))==11
    with pytest.raises(ValueError,match='EXACT_CANDIDATE'):validate_frozen(frozen,trade,DAY)
