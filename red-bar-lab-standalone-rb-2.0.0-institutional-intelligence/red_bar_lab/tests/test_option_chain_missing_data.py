from __future__ import annotations

import pandas as pd

from red_bar_lab.brokers.upstox_client import UpstoxClient


def test_missing_option_chain_values_remain_missing():
    frame = UpstoxClient.option_chain_to_dataframe([
        {
            "expiry": "2026-08-27",
            "underlying_spot_price": None,
            "strike_price": 25000,
            "call_options": {
                "market_data": {
                    "ltp": 100,
                    "close_price": None,
                    "oi": 5000,
                    "prev_oi": None,
                },
                "option_greeks": {"iv": None},
            },
            "put_options": {
                "market_data": {
                    "ltp": 0,
                    "close_price": 0,
                    "oi": 0,
                    "prev_oi": 0,
                },
                "option_greeks": {"iv": 0},
            },
        }
    ])

    row = frame.iloc[0]
    assert pd.isna(row["spot"])
    assert pd.isna(row["call_close"])
    assert pd.isna(row["call_price_change"])
    assert pd.isna(row["call_prev_oi"])
    assert pd.isna(row["call_oi_change"])
    assert pd.isna(row["call_iv"])


def test_real_zero_is_not_treated_as_missing():
    frame = UpstoxClient.option_chain_to_dataframe([
        {
            "expiry": "2026-08-27",
            "underlying_spot_price": 0,
            "strike_price": 0,
            "call_options": {
                "market_data": {
                    "ltp": 0,
                    "close_price": 0,
                    "oi": 0,
                    "prev_oi": 0,
                },
                "option_greeks": {"iv": 0},
            },
            "put_options": {},
        }
    ])

    row = frame.iloc[0]
    assert row["spot"] == 0
    assert row["call_price_change"] == 0
    assert row["call_oi_change"] == 0
    assert row["call_iv"] == 0
