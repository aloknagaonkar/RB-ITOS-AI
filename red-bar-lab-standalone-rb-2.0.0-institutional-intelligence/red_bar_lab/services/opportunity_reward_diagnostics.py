from __future__ import annotations


MINIMUM_REWARD_REMAINING_PCT = 40.0


def _num(value, default=0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def build_opportunity_reward_trace(
    opportunity: dict[str, object],
    signal: dict[str, object] | None = None,
) -> dict[str, object]:
    """Reconstruct the persisted Opportunity reward-consumption decision.

    Read-only diagnostic mirror of OpportunityIntelligenceEngine._reward_remaining.
    It never changes the stored evaluation or execution decision.
    """
    signal = signal or {}
    direction = str(opportunity.get("direction") or signal.get("direction") or "").upper()
    high = _num(signal.get("confirmation_high"))
    low = _num(signal.get("confirmation_low"))
    close = _num(signal.get("confirmation_close"), _num(signal.get("underlying_entry")))

    persisted_remaining = _num(opportunity.get("reward_remaining_pct"), 100.0)
    persisted_consumed = _num(opportunity.get("move_consumed_pct"), 0.0)
    reason = str(opportunity.get("reason") or "")
    reward_blocked = "REWARD_CONSUMED" in reason.upper()

    candle_range = max(high - low, abs(close) * 0.0005, 0.01) if close else max(high - low, 0.01)
    full_consumption_distance = 2.0 * candle_range
    # The spot price used at evaluation time is not currently persisted in
    # opportunity_evaluations. Infer progress from the persisted consumed pct.
    inferred_progress = full_consumption_distance * persisted_consumed / 100.0
    if direction == "BULLISH":
        inferred_spot = close + inferred_progress if close else None
        threshold_spot = close + full_consumption_distance * (1.0 - MINIMUM_REWARD_REMAINING_PCT / 100.0) if close else None
    elif direction == "BEARISH":
        inferred_spot = close - inferred_progress if close else None
        threshold_spot = close - full_consumption_distance * (1.0 - MINIMUM_REWARD_REMAINING_PCT / 100.0) if close else None
    else:
        inferred_spot = None
        threshold_spot = None

    return {
        "signal_id": opportunity.get("signal_id"),
        "candidate_symbol": opportunity.get("candidate_symbol"),
        "direction": direction,
        "entry_mode": opportunity.get("entry_mode"),
        "signal_age_seconds": opportunity.get("signal_age_seconds"),
        "confirmation_high": high or None,
        "confirmation_low": low or None,
        "confirmation_close": close or None,
        "confirmation_range": round(candle_range, 4),
        "full_consumption_distance_2x_range": round(full_consumption_distance, 4),
        "persisted_reward_remaining_pct": round(persisted_remaining, 2),
        "persisted_move_consumed_pct": round(persisted_consumed, 2),
        "minimum_reward_remaining_pct": MINIMUM_REWARD_REMAINING_PCT,
        "maximum_move_consumed_before_block_pct": round(100.0 - MINIMUM_REWARD_REMAINING_PCT, 2),
        "inferred_progress_points": round(inferred_progress, 4),
        "inferred_evaluation_spot": round(inferred_spot, 4) if inferred_spot is not None else None,
        "reward_consumed_threshold_spot": round(threshold_spot, 4) if threshold_spot is not None else None,
        "reward_gate_status": "BLOCK" if reward_blocked else "PASS",
        "reward_gate_reason": (
            f"Persisted reward remaining {persisted_remaining:.2f}% is below the current "
            f"{MINIMUM_REWARD_REMAINING_PCT:.2f}% minimum."
            if reward_blocked else
            f"Persisted reward remaining {persisted_remaining:.2f}% is not terminally blocked."
        ),
        "opportunity_score": opportunity.get("opportunity_score"),
        "reward_score": opportunity.get("reward_score"),
        "structure_valid": opportunity.get("structure_valid"),
        "opposite_red_bar": opportunity.get("opposite_red_bar"),
        "eligible": opportunity.get("eligible"),
        "decision": opportunity.get("decision"),
        "reason": reason,
        "evaluated_at": opportunity.get("evaluated_at"),
        "spot_persistence_note": (
            "Evaluation-time spot is not stored in opportunity_evaluations; displayed spot is reconstructed "
            "from the persisted move-consumed percentage and the same 2x confirmation-range model."
        ),
    }
