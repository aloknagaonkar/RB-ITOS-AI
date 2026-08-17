from __future__ import annotations

from red_bar_lab.ui.strategy_contract_safeguards import (
    POLICIES,
    apply_contract_safeguards,
)


def _row(**overrides):
    row = {
        "instrument_key": "NSE_FO|OPT-1",
        "trading_symbol": "NIFTY OPT-1 PE",
        "option_side": "PE",
        "expiry": "2026-08-20",
        "strike": 25000.0,
        "ltp": 100.0,
        "bid": 99.0,
        "ask": 101.0,
        "spread_pct": 2.0,
        "volume": 1000.0,
        "oi": 5000.0,
        "liquidity_ready": True,
    }
    row.update(overrides)
    return row


def _readiness(rows, *, bundle="2026-08-17T10:00:00+05:30", snapshot="2026-08-17T09:59:30+05:30"):
    return {
        "outcome": "READY_FOR_RANKING",
        "reason": "ready",
        "strategy_id": "RED_BAR",
        "bundle_id": "BUNDLE-1",
        "signal_id": "SIGNAL-1",
        "requested_side": "PE",
        "bundle_timestamp": bundle,
        "snapshot_timestamp": snapshot,
        "contract_rows": rows,
    }


def test_fresh_contract_with_absolute_liquidity_passes_for_ranking():
    result = apply_contract_safeguards(
        _readiness([_row()]),
        policy=POLICIES["RED_BAR"],
    )

    assert result["outcome"] == "READY_FOR_RANKING"
    assert result["snapshot_freshness"] == "FRESH"
    assert result["hard_safeguard_pass_count"] == 1
    assert result["contract_rows"][0]["liquidity_ready"] is True


def test_snapshot_older_than_policy_is_not_ranked():
    result = apply_contract_safeguards(
        _readiness([_row()], snapshot="2026-08-17T09:58:00+05:30"),
        policy=POLICIES["RED_BAR"],
    )

    assert result["outcome"] == "WAIT"
    assert result["snapshot_freshness"] == "STALE"
    assert result["contract_rows"] == []


def test_future_snapshot_is_rejected_as_lookahead():
    result = apply_contract_safeguards(
        _readiness([_row()], snapshot="2026-08-17T10:00:01+05:30"),
        policy=POLICIES["RED_BAR"],
    )

    assert result["outcome"] == "UNAVAILABLE"
    assert result["snapshot_freshness"] == "INVALID_FUTURE"


def test_expired_contract_is_blocked():
    result = apply_contract_safeguards(
        _readiness([_row(expiry="2026-08-16")]),
        policy=POLICIES["RED_BAR"],
    )

    assert result["outcome"] == "REJECTED"
    assert "EXPIRED_CONTRACT" in result["contract_rows"][0]["safeguard_reasons"]


def test_zero_volume_zero_oi_and_wide_spread_are_hard_failures():
    result = apply_contract_safeguards(
        _readiness([_row(volume=0.0, oi=0.0, spread_pct=7.0)]),
        policy=POLICIES["RED_BAR"],
    )

    reasons = result["contract_rows"][0]["safeguard_reasons"]
    assert result["outcome"] == "REJECTED"
    assert "VOLUME_BELOW_MINIMUM" in reasons
    assert "OPEN_INTEREST_BELOW_MINIMUM" in reasons
    assert "SPREAD_TOO_WIDE" in reasons


def test_mixed_expiries_are_blocked():
    result = apply_contract_safeguards(
        _readiness([_row(), _row(instrument_key="NSE_FO|OPT-2", expiry="2026-08-27")]),
        policy=POLICIES["RED_BAR"],
    )

    assert result["outcome"] == "REJECTED"
    assert all("MIXED_EXPIRY_ARTIFACT" in row["safeguard_reasons"] for row in result["contract_rows"])


def test_missing_execution_metadata_is_visible_but_not_fabricated():
    result = apply_contract_safeguards(
        _readiness([_row()]),
        policy=POLICIES["RED_BAR"],
    )
    row = result["contract_rows"][0]

    assert row["hard_safeguard_pass"] is True
    assert row["execution_metadata_ready"] is False
    assert "MISSING_EXPLICIT_INSTRUMENT_TOKEN" in row["execution_metadata_reasons"]
    assert "MISSING_LOT_SIZE" in row["execution_metadata_reasons"]


def test_safeguards_remain_read_only():
    import red_bar_lab.ui.strategy_contract_safeguards as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "submit_order" not in source
    assert "create_candidate" not in source
    assert "mark_bundle_consumed" not in source
    assert "reserve_contract" not in source
    assert "update_position" not in source
