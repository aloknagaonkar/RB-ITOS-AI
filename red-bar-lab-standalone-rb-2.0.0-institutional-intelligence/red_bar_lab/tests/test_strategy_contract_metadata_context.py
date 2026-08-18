from __future__ import annotations

import pandas as pd

from red_bar_lab.ui.strategy_contract_market_context import enrich_contract_market_context
from red_bar_lab.ui.strategy_contract_metadata_context import enrich_contract_execution_metadata


SNAPSHOT = "2026-08-18T09:20:00+05:30"
BUNDLE = "2026-08-18T09:20:10+05:30"


class Database:
    def __init__(self, rows):
        self.rows = rows

    def read_option_chain_history(self, instrument_key, start_date, end_date, limit=2000):
        return list(self.rows)


def chain():
    return pd.DataFrame([
        {
            "strike": 25000,
            "call_instrument_token": "111",
            "call_instrument_key": "NFO|111",
            "call_tradingsymbol": "NIFTY26AUG25000CE",
            "call_exchange": "NFO",
            "call_lot_size": 75,
            "call_tick_size": 0.05,
            "call_expiry": "2026-08-27",
            "call_ltp": 100.0,
            "call_bid": 99.5,
            "call_ask": 100.5,
            "spot_price": 25020.0,
        },
        {
            "strike": 25100,
            "call_instrument_token": "112",
            "call_tradingsymbol": "NIFTY26AUG25100CE",
            "call_exchange": "NFO",
            "call_lot_size": 75,
            "call_tick_size": 0.05,
            "call_expiry": "2026-08-27",
            "call_ltp": 60.0,
            "call_bid": 59.5,
            "call_ask": 60.5,
            "spot_price": 25020.0,
        },
    ])


def readiness():
    return {
        "outcome": "READY_FOR_RANKING",
        "bundle_timestamp": BUNDLE,
        "snapshot_timestamp": SNAPSHOT,
        "ready_for_ranking": 1,
        "contract_rows": [
            {
                "instrument_key": "Unavailable",
                "instrument_token": None,
                "trading_symbol": "Unavailable",
                "exchange": None,
                "lot_size": None,
                "tick_size": None,
                "option_side": "CE",
                "strike": 25000.0,
                "liquidity_ready": True,
            }
        ],
    }


def snapshot_rows(with_spot=True):
    row = {
        "collector_mode": "ONLINE",
        "snapshot_timestamp": SNAPSHOT,
        "chain_artifact_path": "ignored.csv",
    }
    if with_spot:
        row["spot_price"] = 25020.0
    return [row]


def test_restores_execution_metadata_from_exact_artifact():
    result = enrich_contract_execution_metadata(
        readiness(),
        database=Database(snapshot_rows()),
        instrument_key="NSE_INDEX|Nifty 50",
        artifact_loader=lambda path: chain(),
    )
    row = result["contract_rows"][0]
    assert row["instrument_token"] == "111"
    assert row["instrument_key"] == "NFO|111"
    assert row["trading_symbol"] == "NIFTY26AUG25000CE"
    assert row["exchange"] == "NFO"
    assert row["lot_size"] == 75
    assert row["tick_size"] == 0.05
    assert row["expiry"] == "2026-08-27"
    assert row["execution_metadata_complete"] is True
    assert result["metadata_context_status"] == "READY"


def test_matches_contract_by_strike_not_artifact_row_order():
    values = readiness()
    values["contract_rows"][0]["strike"] = 25100.0
    result = enrich_contract_execution_metadata(
        values,
        database=Database(snapshot_rows()),
        instrument_key="NSE_INDEX|Nifty 50",
        artifact_loader=lambda path: chain(),
    )
    assert result["contract_rows"][0]["instrument_token"] == "112"


def test_does_not_use_later_snapshot():
    later = {
        "collector_mode": "ONLINE",
        "snapshot_timestamp": "2026-08-18T09:21:00+05:30",
        "chain_artifact_path": "ignored.csv",
    }
    result = enrich_contract_execution_metadata(
        readiness(),
        database=Database([later]),
        instrument_key="NSE_INDEX|Nifty 50",
        artifact_loader=lambda path: chain(),
    )
    assert result["metadata_context_status"] == "UNAVAILABLE"
    assert result["contract_rows"][0]["instrument_token"] is None


def test_market_context_derives_atm_and_keeps_rankable_when_ready():
    result = enrich_contract_market_context(
        readiness(),
        database=Database(snapshot_rows(with_spot=True)),
        instrument_key="NSE_INDEX|Nifty 50",
        artifact_loader=lambda path: chain(),
    )
    assert result["spot_price"] == 25020.0
    assert result["atm_strike"] == 25000.0
    assert result["market_context_status"] == "READY"
    assert result["outcome"] == "READY_FOR_RANKING"
    assert result["contract_rows"][0]["execution_metadata_complete"] is True


def test_missing_spot_or_atm_forces_wait_before_ranking():
    no_spot_chain = chain().drop(columns=["spot_price"])
    result = enrich_contract_market_context(
        readiness(),
        database=Database(snapshot_rows(with_spot=False)),
        instrument_key="NSE_INDEX|Nifty 50",
        artifact_loader=lambda path: no_spot_chain,
    )
    assert result["market_context_status"] == "UNAVAILABLE"
    assert result["outcome"] == "WAIT"
    assert result["ready_for_ranking"] == 0
    assert "spot and ATM" in result["reason"]


def test_metadata_enrichment_is_read_only():
    original = readiness()
    result = enrich_contract_execution_metadata(
        original,
        database=Database(snapshot_rows()),
        instrument_key="NSE_INDEX|Nifty 50",
        artifact_loader=lambda path: chain(),
    )
    assert original["contract_rows"][0]["instrument_token"] is None
    assert result["metadata_context_read_only"] is True
    assert result["contract_rows"][0]["metadata_context_read_only"] is True


def test_known_nifty_upstox_key_receives_controlled_execution_metadata():
    values = readiness()
    values["contract_rows"][0]["instrument_key"] = "NSE_FO|1002"
    sparse_chain = pd.DataFrame([
        {
            "strike": 25000,
            "call_instrument_key": "NSE_FO|1002",
            "call_expiry": "2026-08-27",
            "spot_price": 25020.0,
        }
    ])

    result = enrich_contract_execution_metadata(
        values,
        database=Database(snapshot_rows()),
        instrument_key="NSE_INDEX|Nifty 50",
        artifact_loader=lambda path: sparse_chain,
    )

    row = result["contract_rows"][0]
    assert result["metadata_context_status"] == "READY"
    assert row["instrument_token"] == "1002"
    assert row["trading_symbol"] == "NSE_FO|1002"
    assert row["exchange"] == "NSE_FO"
    assert row["lot_size"] == 75.0
    assert row["tick_size"] == 0.05
    assert row["execution_metadata_sources"]["lot_size"].startswith("STATIC_POLICY:")


def test_unknown_underlying_does_not_receive_nifty_policy():
    values = readiness()
    values["contract_rows"][0]["instrument_key"] = "NSE_FO|1002"
    sparse_chain = pd.DataFrame([
        {
            "strike": 25000,
            "call_instrument_key": "NSE_FO|1002",
        }
    ])

    result = enrich_contract_execution_metadata(
        values,
        database=Database(snapshot_rows()),
        instrument_key="NSE_INDEX|Unknown Index",
        artifact_loader=lambda path: sparse_chain,
    )

    assert result["metadata_context_status"] == "UNAVAILABLE"
    assert result["metadata_complete_count"] == 0
