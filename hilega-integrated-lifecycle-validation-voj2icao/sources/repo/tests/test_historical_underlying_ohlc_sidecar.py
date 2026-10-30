from datetime import date, datetime, timezone

from market_lab.historical_underlying_ohlc_sidecar import reconstruct_session


class Candle:
    def __init__(self, minute, o, h, l, c, volume=10):
        self.timestamp = datetime(2026, 8, 12, 9, minute, tzinfo=timezone.utc)
        self.open = o
        self.high = h
        self.low = l
        self.close = c
        self.volume = volume


class Gateway:
    def historical_candles(self, instrument_key, session_date):
        return [Candle(15, 100, 105, 99, 104)]


def test_reconstruct_underlying_session():
    session = reconstruct_session(
        Gateway(),
        "NSE_INDEX|Nifty 50",
        date(2026, 8, 12),
    )
    assert session.status == "AVAILABLE"
    assert session.row_count == 1
    assert session.rows[0].open == 100
    assert session.rows[0].close == 104
