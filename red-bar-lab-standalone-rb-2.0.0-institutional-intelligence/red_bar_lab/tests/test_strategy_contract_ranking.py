from __future__ import annotations

from red_bar_lab.ui.strategy_contract_ranking import POLICIES, rank_strategy_contracts


def _row(key: str, *, spread: float, volume: float, oi: float, delta: float | None = None):
    return {
        "instrument_key": key,
        "trading_symbol": key,
        "option_side": "PE",
        "expiry": "2026-08-20",
        "strike": 25000 + int(key[-1]) * 50,
        "ltp": 100.0,
        "bid": 99.0,
        "ask": 101.0,
        "spread_pct": spread,
        "volume": volume,
        "oi": oi,
        "iv": 14.0,
        "delta": delta,
        "liquidity_ready": True,
    }


def _readiness(rows, outcome="READY_FOR_RANKING"):
    return {
        "outcome": outcome,
        "reason": "ready",
        "bundle_id": "BUNDLE-1",
        "signal_id": "SIGNAL-1",
        "requested_side": "PE",
        "snapshot_timestamp": "2026-08-17T10:00:00+05:30",
        "contract_rows": rows,
    }


def test_red_bar_and_dri_propose_at_most_one_contract():
    rows = [_row("OPT1", spread=1.0, volume=1000, oi=5000), _row("OPT2", spread=2.0, volume=500, oi=3000)]
    red_bar = rank_strategy_contracts(_readiness(rows), policy=POLICIES["RED_BAR"])
    dri = rank_strategy_contracts(_readiness(rows), policy=POLICIES["DIRECTIONAL_REGIME_INTELLIGENCE"])

    assert red_bar["outcome"] == "SELECTED"
    assert red_bar["selected_count"] == 1
    assert dri["selected_count"] == 1
    assert red_bar["selected_rows"][0]["ranking_decision"] == "PRIMARY"


def test_rsi_proposes_two_distinct_contracts_with_primary_and_fallback():
    rows = [
        _row("OPT1", spread=1.0, volume=1000, oi=5000, delta=-0.50),
        _row("OPT2", spread=1.5, volume=900, oi=4500, delta=-0.45),
        _row("OPT3", spread=3.0, volume=200, oi=1000, delta=-0.20),
    ]
    result = rank_strategy_contracts(_readiness(rows), policy=POLICIES["RSI_EXTREME_REVERSAL"])

    assert result["outcome"] == "SELECTED"
    assert result["selected_count"] == 2
    assert len({row["instrument_key"] for row in result["selected_rows"]}) == 2
    assert result["selected_rows"][0]["ranking_decision"] == "PRIMARY"
    assert result["selected_rows"][1]["ranking_decision"] == "FALLBACK"


def test_rsi_returns_partial_when_only_one_distinct_contract_is_eligible():
    duplicate = _row("OPT1", spread=1.0, volume=1000, oi=5000)
    result = rank_strategy_contracts(
        _readiness([duplicate, dict(duplicate)]),
        policy=POLICIES["RSI_EXTREME_REVERSAL"],
    )

    assert result["outcome"] == "PARTIAL"
    assert result["selected_count"] == 1
    assert any(row["ranking_decision"] == "DUPLICATE_EXCLUDED" for row in result["ranked_rows"])


def test_non_ready_section_5a_outcome_is_propagated_without_ranking():
    result = rank_strategy_contracts(
        _readiness([], outcome="NOT_ELIGIBLE"),
        policy=POLICIES["RED_BAR"],
    )

    assert result["outcome"] == "NOT_ELIGIBLE"
    assert result["ranked_rows"] == []
    assert result["selected_rows"] == []


def test_non_liquidity_ready_rows_cannot_rank():
    row = _row("OPT1", spread=1.0, volume=1000, oi=5000)
    row["liquidity_ready"] = False
    result = rank_strategy_contracts(_readiness([row]), policy=POLICIES["RED_BAR"])

    assert result["outcome"] == "REJECTED"
    assert result["selected_count"] == 0


def test_ranking_is_deterministic_for_equal_scores():
    rows = [
        _row("OPT2", spread=1.0, volume=1000, oi=5000),
        _row("OPT1", spread=1.0, volume=1000, oi=5000),
    ]
    first = rank_strategy_contracts(_readiness(rows), policy=POLICIES["RED_BAR"])
    second = rank_strategy_contracts(_readiness(list(reversed(rows))), policy=POLICIES["RED_BAR"])

    assert first["selected_rows"][0]["instrument_key"] == "OPT1"
    assert second["selected_rows"][0]["instrument_key"] == "OPT1"


def test_ranking_remains_read_only():
    result = rank_strategy_contracts(
        _readiness([_row("OPT1", spread=1.0, volume=1000, oi=5000)]),
        policy=POLICIES["RED_BAR"],
    )
    assert result["persisted"] is False
    assert result["reserved"] is False
    assert result["executed"] is False

    import red_bar_lab.ui.strategy_contract_ranking as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "submit_order" not in source
    assert "create_candidate" not in source
    assert "mark_bundle_consumed" not in source
    assert "reserve_contract" not in source
