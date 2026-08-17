from __future__ import annotations

import pandas as pd

from red_bar_lab.ui.strategy_contract_readiness import (
    build_contract_data_readiness,
    normalize_contract_rows,
)


class _Database:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    def read_option_chain_history(self, instrument_key, date_from, date_to, limit=500):
        self.calls.append((instrument_key, date_from, date_to, limit))
        return list(self.rows)


def _gate(**overrides):
    value = {
        "eligible": True,
        "final_outcome": "FORWARD_TO_CONTRACT_SELECTION",
        "blocking_reason": "None",
        "strategy_owner": "RSI Extreme Reversal",
        "strategy_id": "RSI_EXTREME_REVERSAL",
        "signal_id": "RSI-SIG-1",
        "bundle_id": "RSI-BND-1",
        "normalized_intent": "BUY PE",
    }
    value.update(overrides)
    return value


def _resolution(created_at="2026-08-17T13:05:00+05:30"):
    return {
        "bundle_rows": [
            {"field": "Created at", "value": created_at},
            {"field": "Fresh until", "value": "2026-08-17T13:10:00+05:30"},
        ],
        "bundle_id": "RSI-BND-1",
    }


def _snapshot(timestamp, path="chain.csv"):
    return {
        "instrument_key": "NSE_INDEX|Nifty 50",
        "trading_date": "2026-08-17",
        "snapshot_timestamp": timestamp,
        "collector_mode": "ONLINE",
        "option_expiry": "2026-08-20",
        "chain_artifact_path": path,
    }


def _chain():
    return pd.DataFrame(
        [
            {
                "strike": 25000,
                "call_instrument_key": "CE-25000",
                "call_ltp": 120,
                "call_bid": 119,
                "call_ask": 121,
                "call_volume": 1000,
                "call_oi": 5000,
                "put_instrument_key": "PE-25000",
                "put_ltp": 110,
                "put_bid": 109,
                "put_ask": 111,
                "put_volume": 1200,
                "put_oi": 6000,
                "put_iv": 14.5,
                "put_delta": -0.48,
            },
            {
                "strike": 25100,
                "call_instrument_key": "CE-25100",
                "call_ltp": 80,
                "call_bid": 79,
                "call_ask": 81,
                "call_volume": 900,
                "call_oi": 4500,
                "put_instrument_key": "PE-25100",
                "put_ltp": 155,
                "put_bid": 154,
                "put_ask": 156,
                "put_volume": 1300,
                "put_oi": 6500,
                "put_iv": 15.0,
                "put_delta": -0.55,
            },
        ]
    )


def test_blocked_gate_evaluates_zero_contracts_and_does_not_query_database():
    database = _Database([])
    result = build_contract_data_readiness(
        gate=_gate(eligible=False, blocking_reason="bundle=STALE; outcome=HOLD"),
        resolution=_resolution(),
        database=database,
        instrument_key="NSE_INDEX|Nifty 50",
        artifact_loader=lambda path: _chain(),
    )

    assert result["outcome"] == "NOT_ELIGIBLE"
    assert result["requested_side_contracts"] == 0
    assert result["ready_for_ranking"] == 0
    assert database.calls == []


def test_nearest_snapshot_at_or_before_bundle_is_used_without_lookahead():
    database = _Database(
        [
            _snapshot("2026-08-17T13:04:00+05:30", "before.csv"),
            _snapshot("2026-08-17T13:06:00+05:30", "future.csv"),
            _snapshot("2026-08-17T13:03:00+05:30", "older.csv"),
        ]
    )
    loaded = []

    def loader(path):
        loaded.append(path)
        return _chain()

    result = build_contract_data_readiness(
        gate=_gate(),
        resolution=_resolution("2026-08-17T13:05:00+05:30"),
        database=database,
        instrument_key="NSE_INDEX|Nifty 50",
        artifact_loader=loader,
    )

    assert result["outcome"] == "READY_FOR_RANKING"
    assert result["snapshot_timestamp"].startswith("2026-08-17T13:04:00")
    assert loaded == ["before.csv"]
    assert result["requested_side_contracts"] == 2
    assert result["ready_for_ranking"] == 2


def test_missing_prior_snapshot_returns_unavailable_instead_of_using_future_data():
    database = _Database([_snapshot("2026-08-17T13:06:00+05:30", "future.csv")])
    result = build_contract_data_readiness(
        gate=_gate(),
        resolution=_resolution("2026-08-17T13:05:00+05:30"),
        database=database,
        instrument_key="NSE_INDEX|Nifty 50",
        artifact_loader=lambda path: _chain(),
    )

    assert result["outcome"] == "UNAVAILABLE"
    assert result["snapshot_relation"] == "UNAVAILABLE"
    assert result["requested_side_contracts"] == 0


def test_requested_side_isolated_and_contracts_are_not_fabricated():
    rows = normalize_contract_rows(
        _chain(),
        side="PE",
        snapshot_timestamp="2026-08-17T13:04:00+05:30",
        expiry="2026-08-20",
    )

    assert [row["instrument_key"] for row in rows] == ["PE-25000", "PE-25100"]
    assert all(row["option_side"] == "PE" for row in rows)
    assert all(row["liquidity_ready"] is True for row in rows)
    assert all(row["decision"] == "READY_FOR_RANKING" for row in rows)


def test_missing_liquidity_fields_waits_but_preserves_base_contract_readiness():
    chain = pd.DataFrame(
        [{"strike": 25000, "put_instrument_key": "PE-25000", "put_ltp": 110}]
    )
    database = _Database([_snapshot("2026-08-17T13:04:00+05:30")])
    result = build_contract_data_readiness(
        gate=_gate(),
        resolution=_resolution(),
        database=database,
        instrument_key="NSE_INDEX|Nifty 50",
        artifact_loader=lambda path: chain,
    )

    assert result["outcome"] == "WAIT"
    assert result["requested_side_contracts"] == 1
    assert result["ready_for_ranking"] == 0
    assert "MISSING_BID_ASK" in result["contract_rows"][0]["reasons"]
    assert "MISSING_VOLUME" in result["contract_rows"][0]["reasons"]
    assert "MISSING_OPEN_INTEREST" in result["contract_rows"][0]["reasons"]


def test_missing_identity_or_price_is_rejected_before_ranking():
    chain = pd.DataFrame(
        [{"strike": 25000, "put_bid": 109, "put_ask": 111, "put_volume": 1000, "put_oi": 5000}]
    )
    database = _Database([_snapshot("2026-08-17T13:04:00+05:30")])
    result = build_contract_data_readiness(
        gate=_gate(),
        resolution=_resolution(),
        database=database,
        instrument_key="NSE_INDEX|Nifty 50",
        artifact_loader=lambda path: chain,
    )

    assert result["outcome"] == "REJECTED"
    assert "MISSING_INSTRUMENT_ID" in result["contract_rows"][0]["reasons"]
    assert "MISSING_PRICE" in result["contract_rows"][0]["reasons"]


def test_section_5a_module_contains_no_write_or_execution_action():
    import red_bar_lab.ui.strategy_contract_readiness as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "submit_order" not in source
    assert "create_candidate" not in source
    assert "mark_bundle_consumed" not in source
    assert "reserve_contract" not in source
    assert "update_position" not in source
