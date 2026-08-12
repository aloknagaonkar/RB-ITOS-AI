from datetime import date

import pandas as pd

from red_bar_lab.market.paper_adapter import UpstoxPaperMarketAdapter
from red_bar_lab.market.upstox_intelligence import (
    UnifiedUpstoxMarketIntelligenceService,
)


class FakeUpstoxProvider:
    def __init__(self):
        self.chain_calls = 0
        self.contract_calls = 0

    def option_expiries(self, underlying_key):
        return ["2026-08-13"]

    def option_chain(self, underlying_key, expiry):
        self.chain_calls += 1
        return [{"fake": True}]

    def option_chain_dataframe(self, records):
        return pd.DataFrame([
            {
                "expiry": "2026-08-13",
                "spot": 25010.0,
                "strike": 25000.0,
                "call_instrument_key": "NSE_FO|1001",
                "call_ltp": 120.0,
                "call_volume": 100000,
                "call_oi": 150000,
                "call_prev_oi": 140000,
                "call_oi_change": 10000,
                "call_bid": 119.5,
                "call_bid_qty": 750,
                "call_ask": 120.5,
                "call_ask_qty": 900,
                "call_iv": 14.5,
                "call_delta": 0.52,
                "call_gamma": 0.02,
                "call_theta": -3.1,
                "call_vega": 4.4,
                "call_pop": 51.0,
                "put_instrument_key": "NSE_FO|1002",
                "put_ltp": 110.0,
                "put_volume": 90000,
                "put_oi": 180000,
                "put_prev_oi": 170000,
                "put_oi_change": 10000,
                "put_bid": 109.5,
                "put_bid_qty": 800,
                "put_ask": 110.5,
                "put_ask_qty": 850,
                "put_iv": 15.0,
                "put_delta": -0.48,
                "put_gamma": 0.02,
                "put_theta": -3.0,
                "put_vega": 4.3,
                "put_pop": 49.0,
            },
            {
                "expiry": "2026-08-13",
                "spot": 25010.0,
                "strike": 25100.0,
                "call_instrument_key": "NSE_FO|1003",
                "call_ltp": 80.0,
                "call_volume": 80000,
                "call_oi": 250000,
                "call_prev_oi": 240000,
                "call_oi_change": 10000,
                "call_bid": 79.5,
                "call_bid_qty": 700,
                "call_ask": 80.5,
                "call_ask_qty": 700,
                "call_iv": 15.0,
                "call_delta": 0.40,
                "call_gamma": 0.018,
                "call_theta": -2.8,
                "call_vega": 4.0,
                "call_pop": 42.0,
                "put_instrument_key": "NSE_FO|1004",
                "put_ltp": 150.0,
                "put_volume": 70000,
                "put_oi": 100000,
                "put_prev_oi": 95000,
                "put_oi_change": 5000,
                "put_bid": 149.5,
                "put_bid_qty": 600,
                "put_ask": 150.5,
                "put_ask_qty": 650,
                "put_iv": 15.3,
                "put_delta": -0.60,
                "put_gamma": 0.018,
                "put_theta": -2.9,
                "put_vega": 4.1,
                "put_pop": 58.0,
            },
        ])

    def option_contracts(self, underlying_key, expiry=None):
        self.contract_calls += 1
        return [
            {
                "name": "NIFTY",
                "segment": "NSE_FO",
                "exchange": "NSE",
                "expiry": "2026-08-13",
                "instrument_key": "NSE_FO|1001",
                "exchange_token": "1001",
                "trading_symbol": "NIFTY 25000 CE 13 AUG 26",
                "lot_size": 75,
                "instrument_type": "CE",
                "strike_price": 25000,
            },
            {
                "name": "NIFTY",
                "segment": "NSE_FO",
                "exchange": "NSE",
                "expiry": "2026-08-13",
                "instrument_key": "NSE_FO|1002",
                "exchange_token": "1002",
                "trading_symbol": "NIFTY 25000 PE 13 AUG 26",
                "lot_size": 75,
                "instrument_type": "PE",
                "strike_price": 25000,
            },
        ]

    def intraday_candles(self, instrument_key, interval_minutes=1):
        ts = pd.date_range(
            "2026-08-10 09:15",
            periods=5,
            freq="1min",
            tz="Asia/Kolkata",
        )
        return pd.DataFrame({
            "timestamp": ts,
            "open": [100,101,102,103,104],
            "high": [101,102,103,104,105],
            "low": [99,100,101,102,103],
            "close": [100,101,102,103,104],
            "volume": [1000]*5,
        })

    def historical_candles(
        self, instrument_key, start_date, end_date, interval_minutes=1
    ):
        return self.intraday_candles(instrument_key, interval_minutes)


def test_unified_snapshot_contains_greeks_oi_pcr_and_walls():
    provider = FakeUpstoxProvider()
    service = UnifiedUpstoxMarketIntelligenceService(
        provider,
        cache_ttl_seconds=60,
    )
    snap = service.snapshot(
        underlying_key="NSE_INDEX|Nifty 50"
    )

    assert snap.spot_price == 25010.0
    assert snap.pcr_oi is not None
    assert snap.call_wall == 25100.0
    assert snap.put_wall == 25000.0
    assert "call_delta" in snap.chain.columns
    assert "put_gamma" in snap.chain.columns
    assert "call_iv" in snap.chain.columns

    # Same refresh cycle must reuse the snapshot.
    service.snapshot(underlying_key="NSE_INDEX|Nifty 50")
    assert provider.chain_calls == 1


def test_upstox_paper_adapter_exposes_contracts_quotes_and_candles():
    provider = FakeUpstoxProvider()
    service = UnifiedUpstoxMarketIntelligenceService(provider)
    adapter = UpstoxPaperMarketAdapter(
        service,
        "NIFTY 50",
        "NSE_INDEX|Nifty 50",
    )

    contracts = adapter.nfo_options("NIFTY 50")
    assert len(contracts) == 2
    assert int(contracts.iloc[0]["lot_size"]) == 75

    symbol = str(contracts.iloc[0]["tradingsymbol"])
    quotes = adapter.quote([f"UPSTOX:{symbol}"])
    q = quotes[f"UPSTOX:{symbol}"]
    assert q["last_price"] == 120.0
    assert q["delta"] == 0.52
    assert q["iv"] == 14.5
    assert q["gamma"] == 0.02
    assert q["theta"] == -3.1
    assert q["vega"] == 4.4
    assert q["depth"]["sell"][0]["price"] == 120.5

    candles = adapter.historical_candles(
        int(contracts.iloc[0]["instrument_token"]),
        "minute",
        date.today().isoformat(),
        date.today().isoformat(),
    )
    assert not candles.empty


def test_option_contracts_are_cached():
    provider = FakeUpstoxProvider()
    service = UnifiedUpstoxMarketIntelligenceService(provider)
    service.option_contracts(
        underlying_key="NSE_INDEX|Nifty 50"
    )
    service.option_contracts(
        underlying_key="NSE_INDEX|Nifty 50"
    )
    assert provider.contract_calls == 1
