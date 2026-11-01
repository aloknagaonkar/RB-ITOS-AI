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


class _SourceAwareGateway:
    def __init__(self):
        self.calls = []

    def historical_candles(self, instrument_key, session_date):
        # Underlying minute at the fixed 09:20 anchor.
        return [
            HistoricalCandle(
                provider="upstox",
                instrument_key=instrument_key,
                session_date=session_date,
                timestamp=datetime(session_date.year, session_date.month, session_date.day, 9, 20, tzinfo=IST),
                open=23340.0,
                high=23360.0,
                low=23330.0,
                close=23350.0,
                volume=100,
                open_interest=None,
            )
        ]

    def _contracts(self, underlying, expiry):
        out = []
        for strike in range(23000, 23701, 50):
            for side in ("CE", "PE"):
                out.append(
                    HistoricalOptionContract(
                        instrument_key=f"{side}{strike}",
                        underlying=underlying,
                        expiry=expiry,
                        strike=float(strike),
                        side=side,
                    )
                )
        return out

    def historical_option_contracts(self, underlying, expiry):
        self.calls.append(("expired_contracts", expiry))
        return self._contracts(underlying, expiry)

    def active_option_contracts(self, underlying, expiry):
        self.calls.append(("active_contracts", expiry))
        return self._contracts(underlying, expiry)

    def historical_option_candles(self, instrument_key, session_date):
        self.calls.append(("expired_candles", instrument_key))
        return [self._option_candle(instrument_key, session_date)]

    def active_option_historical_candles(self, instrument_key, session_date):
        self.calls.append(("active_candles", instrument_key))
        return [self._option_candle(instrument_key, session_date)]

    def _option_candle(self, instrument_key, session_date):
        return HistoricalCandle(
            provider="upstox",
            instrument_key=instrument_key,
            session_date=session_date,
            timestamp=datetime(session_date.year, session_date.month, session_date.day, 9, 25, tzinfo=IST),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=10,
            open_interest=20,
        )


def test_active_expiry_uses_active_provider_sources():
    from market_lab.historical_option_ohlc_sidecar import reconstruct_ohlc_session

    g = _SourceAwareGateway()
    session = reconstruct_ohlc_session(
        g,
        "NSE_INDEX|Nifty 50",
        date(2026, 9, 23),
        date(2026, 9, 29),
        2,
        provider_as_of=date(2026, 9, 24),
    )
    assert session.status == "AVAILABLE"
    assert session.row_count > 0
    assert any(c[0] == "active_contracts" for c in g.calls)
    assert any(c[0] == "active_candles" for c in g.calls)
    assert not any(c[0] == "expired_contracts" for c in g.calls)
    assert not any(c[0] == "expired_candles" for c in g.calls)


def test_expired_expiry_uses_expired_provider_sources():
    from market_lab.historical_option_ohlc_sidecar import reconstruct_ohlc_session

    g = _SourceAwareGateway()
    session = reconstruct_ohlc_session(
        g,
        "NSE_INDEX|Nifty 50",
        date(2026, 9, 21),
        date(2026, 9, 22),
        2,
        provider_as_of=date(2026, 9, 24),
    )
    assert session.status == "AVAILABLE"
    assert any(c[0] == "expired_contracts" for c in g.calls)
    assert any(c[0] == "expired_candles" for c in g.calls)
    assert not any(c[0] == "active_contracts" for c in g.calls)
    assert not any(c[0] == "active_candles" for c in g.calls)


def test_zero_contract_catalog_is_unavailable_not_available():
    from market_lab.historical_option_ohlc_sidecar import reconstruct_ohlc_session

    class Empty(_SourceAwareGateway):
        def active_option_contracts(self, underlying, expiry):
            self.calls.append(("active_contracts", expiry))
            return []

    g = Empty()
    session = reconstruct_ohlc_session(
        g,
        "NSE_INDEX|Nifty 50",
        date(2026, 9, 23),
        date(2026, 9, 29),
        2,
        provider_as_of=date(2026, 9, 24),
    )
    assert session.status == "UNAVAILABLE"
    assert session.row_count == 0
    assert session.issues == ("option_contracts_unavailable:active",)
