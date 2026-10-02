from datetime import date, datetime, timedelta, timezone

from market_lab.domain import HistoricalCandle, HistoricalOptionCandleSeries, HistoricalOptionContract
from market_lab.historical_option_ohlc_sidecar import rows_from_series

IST = timezone(timedelta(hours=5, minutes=30))
D = date(2026, 3, 16)
E = date(2026, 3, 17)
T = datetime(2026, 3, 16, 10, 0, tzinfo=IST)


def test_raw_ohlc_sidecar_preserves_full_candle_and_oi():
    contract = HistoricalOptionContract(
        instrument_key="CE23000", underlying="NSE_INDEX|Nifty 50", expiry=E, strike=23000.0, side="CE"
    )
    candle = HistoricalCandle(
        provider="upstox", instrument_key="CE23000", session_date=D, timestamp=T,
        open=100.0, high=110.0, low=95.0, close=105.0, volume=1234, open_interest=5678.0,
    )
    series = HistoricalOptionCandleSeries(contract=contract, session_date=D, candles=[candle])
    row = rows_from_series(underlying="NSE_INDEX|Nifty 50", expiry=E, option_series=[series])[0]
    assert row.open == 100.0
    assert row.high == 110.0
    assert row.low == 95.0
    assert row.close == 105.0
    assert row.volume == 1234
    assert row.open_interest == 5678.0
