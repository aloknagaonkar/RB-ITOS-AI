from pathlib import Path
from datetime import datetime,timedelta
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parent))
import collect,strategy

def instrument(**kw):
    x=dict(instrument_type='FUT',segment='NSE_FO',underlying_symbol='NIFTY',underlying_key=collect.INDEX,instrument_key='NSE_FO|TEST',trading_symbol='NIFTY NOV TEST',expiry='2026-11-23');x.update(kw);return x

def test_month_contract_selection_and_wrong_underlying():
    rows=[instrument(instrument_key='OTHER',underlying_symbol='BANKNIFTY'),instrument(expiry='2026-12-29',instrument_key='DEC'),instrument()]
    assert collect.choose_contract(rows)['instrument_key']=='NSE_FO|TEST'

def test_expired_october_never_reused():
    with pytest.raises(collect.DataError):collect.choose_contract([instrument(expiry='2026-10-27')])

def test_later_month_not_silently_substituted():
    with pytest.raises(collect.DataError):collect.choose_contract([instrument(expiry='2026-12-29')])

def test_exact_five_dates():
    assert collect.DAYS==['2026-10-29','2026-10-30','2026-11-02','2026-11-03','2026-11-04']

def test_normalization_sorts_and_logs_outside_window():
    b={'data':{'candles':[['2026-11-02T15:30:00+05:30',100,101,99,100,1],['2026-11-02T09:16:00+05:30',100,101,99,100,1],['2026-11-02T09:15:00+05:30',100,101,99,100,1]]}}
    rows,out=collect.normalize(b,'2026-11-02')
    assert rows[0]['timestamp'].endswith('09:15:00+05:30')
    assert len(rows)==2 and len(out)==1

def test_duplicate_or_wrong_day_blocks():
    row=['2026-11-02T09:15:00+05:30',100,101,99,100,1]
    with pytest.raises(collect.DataError):collect.normalize({'data':{'candles':[row,row]}},'2026-11-02')
    with pytest.raises(collect.DataError):collect.normalize({'data':{'candles':[row]}},'2026-11-03')

def test_authentication_never_sent_to_order_endpoint():
    with pytest.raises(collect.DataError):collect.get_json('/v2/order/place','DUMMY')

def test_source_matches_frozen_oct26():
    import hashlib,json
    here=Path(__file__).parent
    assert hashlib.sha256((here/'strategy.py').read_bytes()).hexdigest()==json.loads((here/'strategy-pin.json').read_text())['sha256']
