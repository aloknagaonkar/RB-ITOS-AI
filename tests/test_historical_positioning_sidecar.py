from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from market_lab.domain import (
    HistoricalCandle,
    HistoricalOptionCandleSeries,
    HistoricalOptionContract,
    HistoricalOptionSideObservation,
    HistoricalReconstructedSnapshot,
    HistoricalStrikeObservation,
)
from market_lab.historical_positioning import PositioningConfig
from market_lab.historical_positioning_sidecar import build_positioning_rows_from_reconstruction

IST = ZoneInfo("Asia/Kolkata")
D = date(2026, 9, 8)
E = date(2026, 9, 8)
T0 = datetime(2026, 9, 8, 10, 0, tzinfo=IST)


def candle(key, ts, close, oi):
    return HistoricalCandle(provider="upstox", instrument_key=key, session_date=D, timestamp=ts,
        open=close, high=close, low=close, close=close, volume=100, open_interest=oi)


def contract(key, strike, side):
    return HistoricalOptionContract(instrument_key=key, underlying="NSE_INDEX|Nifty 50", expiry=E, strike=strike, side=side)


def test_sidecar_uses_exact_series_baseline_even_when_prior_moving_basket_did_not_contain_strike():
    ce = contract("CE100", 100.0, "CE")
    pe = contract("PE100", 100.0, "PE")
    series = [
        HistoricalOptionCandleSeries(contract=ce, session_date=D, candles=[candle("CE100", T0, 10, 100), candle("CE100", T0+timedelta(minutes=5), 8, 120)]),
        HistoricalOptionCandleSeries(contract=pe, session_date=D, candles=[candle("PE100", T0, 10, 100), candle("PE100", T0+timedelta(minutes=5), 12, 120)]),
    ]
    current = HistoricalStrikeObservation(
        strike=100.0,
        ce=HistoricalOptionSideObservation(side="CE", instrument_key="CE100", close=8, open_interest=120, volume=100, status="AVAILABLE"),
        pe=HistoricalOptionSideObservation(side="PE", instrument_key="PE100", close=12, open_interest=120, volume=100, status="AVAILABLE"),
    )
    snapshot = HistoricalReconstructedSnapshot(
        source_provider="upstox", underlying="NSE_INDEX|Nifty 50", expiry=E, session_date=D,
        timestamp=T0+timedelta(minutes=5), spot=100.0, moving_atm=100.0, wings=0, strike_interval=50,
        strikes=[current], fixed_strikes=[], fixed_anchor_timestamp=None, fixed_atm=None,
    )
    rows = build_positioning_rows_from_reconstruction(snapshots=[snapshot], option_series=series, config=PositioningConfig())
    assert len(rows) == 1
    row = rows[0]
    assert row.ce_5m_state == "SHORT_BUILDUP"
    assert row.pe_5m_state == "LONG_BUILDUP"
    assert row.combined_5m == "STRONG_BEARISH"
    assert row.ce_15m_state == "UNAVAILABLE"


def test_sidecar_preserves_missing_oi_as_unavailable_not_zero():
    ce = contract("CE100", 100.0, "CE")
    pe = contract("PE100", 100.0, "PE")
    series = [
        HistoricalOptionCandleSeries(contract=ce, session_date=D, candles=[candle("CE100", T0, 10, 100), candle("CE100", T0+timedelta(minutes=5), 8, None)]),
        HistoricalOptionCandleSeries(contract=pe, session_date=D, candles=[candle("PE100", T0, 10, 100), candle("PE100", T0+timedelta(minutes=5), 12, 120)]),
    ]
    current = HistoricalStrikeObservation(
        strike=100.0,
        ce=HistoricalOptionSideObservation(side="CE", instrument_key="CE100", close=8, open_interest=None, volume=100, status="OI_UNAVAILABLE"),
        pe=HistoricalOptionSideObservation(side="PE", instrument_key="PE100", close=12, open_interest=120, volume=100, status="AVAILABLE"),
    )
    snapshot = HistoricalReconstructedSnapshot(
        source_provider="upstox", underlying="NSE_INDEX|Nifty 50", expiry=E, session_date=D,
        timestamp=T0+timedelta(minutes=5), spot=100.0, moving_atm=100.0, wings=0, strike_interval=50,
        strikes=[current], fixed_strikes=[], fixed_anchor_timestamp=None, fixed_atm=None,
    )
    row = build_positioning_rows_from_reconstruction(snapshots=[snapshot], option_series=series)[0]
    assert row.ce_open_interest is None
    assert row.ce_5m_oi_change_pct is None
    assert row.ce_5m_state == "UNAVAILABLE"
    assert row.combined_5m == "UNAVAILABLE"
