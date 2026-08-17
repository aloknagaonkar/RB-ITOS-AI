from __future__ import annotations

import pandas as pd

from red_bar_lab.ui.strategy_contract_market_context import enrich_contract_market_context
from red_bar_lab.ui.strategy_contract_safeguards import (
    POLICIES,
    apply_contract_safeguards,
)


class _Database:
    def __init__(self, rows):
        self.rows = rows

    def read_option_chain_history(self, instrument_key, start, end, limit=2000):
        return list(self.rows)


def _readiness():
    return {
        "outcome": "READY_FOR_RANKING",
        "bundle_timestamp": "2026-08-17T10:00:30+05:30",
        "snapshot_timestamp": "2026-08-17T10:00:00+05:30",
        "bundle_id": "BUNDLE-1",
        "signal_id": "SIGNAL-1",
        "requested_side": "CE",
        "contract_rows": [
            {
                "instrument_key": "OPT-ATM",
                "option_side": "CE",
                "expiry": "2026-08-20",
                "strike": 25000.0,
                "spread_pct": 1.0,
                "volume": 1000.0,
                "oi": 5000.0,
                "liquidity_ready": True,
            },
            {
                "instrument_key": "OPT-FAR",
                "option_side": "CE",
                "expiry": "2026-08-20",
                "strike": 25200.0,
                "spread_pct": 1.0,
                "volume": 1000.0,
                "oi": 5000.0,
                "liquidity_ready": True,
            },
        ],
    }


def test_market_context_uses_exact_selected_snapshot_and_nearest_strike_for_atm():
    rows = [
        {
            "collector_mode": "ONLINE",
            "snapshot_timestamp": "2026-08-17T10:00:00+05:30",
            "spot_price": 25020.0,
            "chain_artifact_path": "ignored.csv",
        },
        {
            "collector_mode": "ONLINE",
            "snapshot_timestamp": "2026-08-17T10:00:20+05:30",
            "spot_price": 26000.0,
            "chain_artifact_path": "future.csv",
        },
    ]
    chain = pd.DataFrame({"strike": [24950, 25000, 25050]})
    result = enrich_contract_market_context(
        _readiness(),
        database=_Database(rows),
        instrument_key="NSE_INDEX|Nifty 50",
        artifact_loader=lambda _: chain,
    )

    assert result["market_context_status"] == "READY"
    assert result["spot_price"] == 25020.0
    assert result["atm_strike"] == 25000.0
    assert result["spot_source"] == "SNAPSHOT_METADATA:spot_price"
    assert result["atm_source"] == "NEAREST_AVAILABLE_STRIKE"


def test_market_context_does_not_fall_forward_when_exact_snapshot_is_missing():
    rows = [
        {
            "collector_mode": "ONLINE",
            "snapshot_timestamp": "2026-08-17T10:00:20+05:30",
            "spot_price": 26000.0,
            "chain_artifact_path": "future.csv",
        }
    ]
    result = enrich_contract_market_context(
        _readiness(),
        database=_Database(rows),
        instrument_key="NSE_INDEX|Nifty 50",
        artifact_loader=lambda _: pd.DataFrame({"strike": [26000]}),
    )

    assert result["market_context_status"] == "UNAVAILABLE"
    assert result["spot_price"] is None
    assert result["atm_strike"] is None


def test_strike_distance_hard_blocks_contract_beyond_two_steps():
    readiness = _readiness()
    readiness.update(
        {
            "spot_price": 25020.0,
            "atm_strike": 25000.0,
            "spot_source": "SNAPSHOT_METADATA:spot_price",
            "atm_source": "NEAREST_AVAILABLE_STRIKE",
            "market_context_status": "READY",
            "market_context_reason": "aligned",
        }
    )
    result = apply_contract_safeguards(
        readiness,
        policy=POLICIES["RED_BAR"],
    )

    assert result["strike_safeguard_status"] == "EVALUATED"
    assert result["strike_interval"] == 200.0
    assert result["contract_rows"][0]["moneyness"] == "ATM"
    assert result["contract_rows"][0]["hard_safeguard_pass"] is True
    assert result["contract_rows"][1]["strike_distance_steps"] == 1.0


def test_strike_distance_blocks_three_step_contract():
    readiness = _readiness()
    readiness["contract_rows"] = [
        {
            "instrument_key": f"OPT-{strike}",
            "option_side": "CE",
            "expiry": "2026-08-20",
            "strike": float(strike),
            "spread_pct": 1.0,
            "volume": 1000.0,
            "oi": 5000.0,
            "liquidity_ready": True,
        }
        for strike in (25000, 25050, 25100, 25150)
    ]
    readiness.update(
        {
            "spot_price": 25020.0,
            "atm_strike": 25000.0,
            "market_context_status": "READY",
        }
    )
    result = apply_contract_safeguards(readiness, policy=POLICIES["RED_BAR"])

    far = next(row for row in result["contract_rows"] if row["strike"] == 25150.0)
    assert far["strike_distance_steps"] == 3.0
    assert far["hard_safeguard_pass"] is False
    assert "STRIKE_OUT_OF_RANGE" in far["safeguard_reasons"]


def test_market_context_module_remains_read_only():
    import red_bar_lab.ui.strategy_contract_market_context as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "submit_order" not in source
    assert "create_candidate" not in source
    assert "mark_bundle_consumed" not in source
    assert "reserve_contract" not in source
