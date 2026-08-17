from __future__ import annotations

from red_bar_lab.ui.strategy_candidate_readiness import build_candidate_readiness


def _row(key: str, role: str, side: str = "PE"):
    return {
        "instrument_key": key,
        "instrument_token": f"TOKEN-{key}",
        "trading_symbol": f"NIFTY-{key}",
        "exchange": "NFO",
        "lot_size": 75,
        "tick_size": 0.05,
        "ranking_decision": role,
        "option_side": side,
        "expiry": "2026-08-20",
        "strike": 25000,
        "score": 90.0,
        "spread_quality": 90.0,
        "volume_quality": 80.0,
        "oi_quality": 85.0,
        "delta_quality": 75.0,
        "iv_evidence": 100.0,
        "strike_distance_steps": 0.0,
        "hard_safeguard_pass": True,
        "liquidity_ready": True,
    }


def _resolution():
    return {
        "refreshed_at": "2026-08-17T10:00:30+05:30",
        "bundle_rows": [
            {"field": "Created at", "value": "2026-08-17T10:00:00+05:30"},
            {"field": "Fresh until", "value": "2026-08-17T10:02:00+05:30"},
        ],
    }


def _build(strategy: str, rows, requested_side="PE"):
    return build_candidate_readiness(
        gate={"strategy_id": strategy, "bundle_id": "BUNDLE-1", "signal_id": "SIGNAL-1"},
        resolution=_resolution(),
        safeguarded={
            "bundle_timestamp": "2026-08-17T10:00:00+05:30",
            "snapshot_freshness": "FRESH",
            "snapshot_age_seconds": 10.0,
            "maximum_snapshot_age_seconds": 60.0,
        },
        ranking={
            "strategy_id": strategy,
            "bundle_id": "BUNDLE-1",
            "signal_id": "SIGNAL-1",
            "requested_side": requested_side,
            "selected_rows": rows,
        },
        option_direction={"direction": "BEARISH"},
        evaluation_timestamp="2026-08-17T10:00:30+05:30",
    )


def test_red_bar_primary_reaches_admission_ready_read_only():
    result = _build("RED_BAR", [_row("1", "PRIMARY")])
    candidate = result["candidates"][0]
    assert result["outcome"] == "HANDOFF_READY"
    assert candidate["validation_outcome"] == "HANDOFF_READY"
    assert candidate["lifecycle_state"] == "ADMISSION_READY_READ_ONLY"
    assert candidate["candidate_id"].startswith("RB-CAND-")


def test_dri_primary_uses_canonical_strategy_identity():
    result = _build("DIRECTIONAL_REGIME", [_row("1", "PRIMARY")])
    assert result["candidates"][0]["candidate_id"].startswith("DRI-CAND-")
    assert result["candidates"][0]["validation_outcome"] == "HANDOFF_READY"


def test_rsi_entries_are_independent_candidates():
    result = _build(
        "RSI_EXTREME_REVERSAL",
        [_row("1", "ENTRY_1"), _row("2", "ENTRY_2")],
    )
    assert result["ready_count"] == 2
    assert len({row["identity_key"] for row in result["candidates"]}) == 2
    assert [row["role"] for row in result["candidates"]] == ["ENTRY_1", "ENTRY_2"]


def test_missing_execution_metadata_waits_without_rejecting_other_rsi_entry():
    first = _row("1", "ENTRY_1")
    first["lot_size"] = None
    second = _row("2", "ENTRY_2")
    result = _build("RSI_EXTREME_REVERSAL", [first, second])
    assert result["candidates"][0]["validation_outcome"] == "WAIT"
    assert "MISSING_LOT_SIZE" in result["candidates"][0]["exact_reason"]
    assert result["candidates"][1]["validation_outcome"] == "HANDOFF_READY"


def test_side_mismatch_is_rejected():
    result = _build("RED_BAR", [_row("1", "PRIMARY", side="CE")], requested_side="PE")
    candidate = result["candidates"][0]
    assert candidate["validation_outcome"] == "REJECTED"
    assert "CONTRACT_SIDE_DOES_NOT_MATCH_BUNDLE_INTENT" in candidate["exact_reason"]


def test_invalid_role_is_rejected():
    result = _build("RSI_EXTREME_REVERSAL", [_row("1", "PRIMARY")])
    assert result["candidates"][0]["validation_outcome"] == "REJECTED"
    assert "INVALID_CONTRACT_ROLE" in result["candidates"][0]["exact_reason"]


def test_capacity_is_strategy_owned():
    result = _build(
        "RSI_EXTREME_REVERSAL",
        [_row("1", "ENTRY_1"), _row("2", "ENTRY_2"), _row("3", "ENTRY_2")],
    )
    assert result["capacity"] == 2
    assert result["candidates"][2]["validation_outcome"] == "REJECTED"
    assert "STRATEGY_CAPACITY_EXCEEDED" in result["candidates"][2]["exact_reason"]


def test_candidate_identity_and_score_are_deterministic():
    first = _build("RED_BAR", [_row("1", "PRIMARY")])["candidates"][0]
    second = _build("RED_BAR", [_row("1", "PRIMARY")])["candidates"][0]
    assert first["candidate_id"] == second["candidate_id"]
    assert first["identity_key"] == second["identity_key"]
    assert first["candidate_score"] == second["candidate_score"]
    assert round(sum(item["weight_pct"] for item in first["score_components"]), 6) == 100.0
    assert all("contribution" in item for item in first["score_components"])


def test_candidate_stage_remains_read_only():
    candidate = _build("RED_BAR", [_row("1", "PRIMARY")])["candidates"][0]
    assert candidate["persisted"] is False
    assert candidate["reserved"] is False
    assert candidate["bundle_consumed"] is False
    assert candidate["submitted"] is False

    import red_bar_lab.ui.strategy_candidate_readiness as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "submit_order" not in source
    assert "create_candidate" not in source
    assert "mark_bundle_consumed" not in source
    assert "reserve_contract" not in source
