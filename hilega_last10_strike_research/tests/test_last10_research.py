from datetime import date, datetime, timedelta
from types import SimpleNamespace
import pytest
from hilega_last10_strike_research.run import (
    UNDERLYING, choose_days, freeze_contracts, group_underlying, nearest_expiry,
)


def test_last_ten_are_provider_dates_not_weekday_assumptions():
    days=[f'2026-09-{n:02d}' for n in range(1,14)]
    grouped={d:[{}] for d in days};grouped['2026-09-14']=[]
    assert choose_days(grouped,'2026-09-14')==days[-10:]
    with pytest.raises(ValueError,match='WARMUP'):choose_days({d:[{}] for d in days[-10:]},'2026-09-14')


def test_expiry_schedule_combines_expired_and_active_catalogue():
    active=[dict(expiry='2026-10-19',underlying_key=UNDERLYING)]
    assert nearest_expiry('2026-10-08',['2026-10-06','2026-10-13'],active)=='2026-10-13'
    assert nearest_expiry('2026-10-14',['2026-10-13'],active)=='2026-10-19'
    with pytest.raises(ValueError,match='MISSING'):nearest_expiry('2026-10-20',['2026-10-13'],active)


@pytest.mark.parametrize('side,direction',[('CE','BULLISH'),('PE','BEARISH')])
def test_eleven_contracts_use_confirmed_spot_and_provider_lot(side,direction):
    trade=dict(direction=direction,entry_price=22525,entry_time='2026-10-08T09:30:00+05:30')
    contracts=[SimpleNamespace(side=side,strike=22500+n*50,expiry=date(2026,10,13),instrument_key=str(n),lot_size=65) for n in range(-5,6)]
    frozen=freeze_contracts(trade,contracts,'2026-10-13')
    assert frozen['atm']==22500 and len(frozen['contracts'])==11
    assert frozen['contracts'][-1]['strike']==22750
    assert frozen['contracts'][0]['lot_size']==65
    contracts[0].lot_size=None
    with pytest.raises(ValueError,match='LOT_SIZE'):freeze_contracts(trade,contracts,'2026-10-13')


def test_contract_identity_missing_or_duplicate_is_not_filled_in():
    trade=dict(direction='BULLISH',entry_price=22500,entry_time='2026-10-08T09:30:00+05:30')
    contracts=[SimpleNamespace(side='CE',strike=22500+n*50,expiry=date(2026,10,13),instrument_key=str(n),lot_size=65) for n in range(-5,6)]
    with pytest.raises(ValueError,match='AMBIGUOUS'):freeze_contracts(trade,contracts[:-1],'2026-10-13')
    with pytest.raises(ValueError,match='AMBIGUOUS'):freeze_contracts(trade,contracts+[contracts[0]],'2026-10-13')


def test_provider_candles_grouped_by_ist_day_and_naive_rejected():
    body=dict(data=dict(candles=[['2026-10-08T09:15:00+05:30',22500,22510,22490,22505,0,0],
                                 ['2026-10-09T09:15:00+05:30',22500,22510,22490,22505,0,0]]))
    rows=group_underlying(body)
    assert sorted(rows)==['2026-10-08','2026-10-09']
    body['data']['candles'][0][0]='2026-10-08T09:15:00'
    with pytest.raises(ValueError,match='TIMEZONE'):group_underlying(body)
