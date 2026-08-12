from __future__ import annotations


def _num(value, default=0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def build_committee_gate_trace(
    evaluation: dict[str, object],
    *,
    minimum_execution_probability_pct: float = 70.0,
    minimum_expected_value_pct: float = 0.0,
) -> dict[str, object]:
    """Explain the persisted Committee decision without changing it.

    Authoritative blockers are Performance hard-block, terminal opportunity
    invalidity, and minimum execution probability. Expected Value, Expectancy,
    Expected Win/Loss, Shadow, history score, expectancy confidence and
    Half-Kelly are informational-only.
    """
    reason = str(evaluation.get("reason") or "")
    reason_upper = reason.upper()
    probability = _num(evaluation.get("execution_probability_pct"))
    expectancy = _num(evaluation.get("expectancy_pct"))

    performance_blocked = "PERFORMANCE_HARD_BLOCK[" in reason_upper
    terminal_blocked = "OPPORTUNITY_TERMINAL[" in reason_upper
    probability_blocked = probability < float(minimum_execution_probability_pct)

    gates = [
        {
            "gate": "Performance hard blocker",
            "authority": "HARD",
            "actual": "BLOCKED" if performance_blocked else "CLEAR",
            "threshold": "selection.eligible must be true",
            "status": "BLOCK" if performance_blocked else "PASS",
            "detail": (
                "PERFORMANCE_HARD_BLOCK is present in the persisted Committee reason."
                if performance_blocked
                else "No PERFORMANCE_HARD_BLOCK is present."
            ),
        },
        {
            "gate": "Opportunity terminal validity",
            "authority": "HARD",
            "actual": "TERMINAL" if terminal_blocked else "VALID",
            "threshold": "No STRUCTURE_INVALID / OPPOSITE_RED_BAR / EMA10 trend loss",
            "status": "BLOCK" if terminal_blocked else "PASS",
            "detail": (
                "Persisted reason contains OPPORTUNITY_TERMINAL."
                if terminal_blocked
                else "No terminal opportunity invalidity is present."
            ),
        },
        {
            "gate": "Execution probability",
            "authority": "HARD",
            "actual": round(probability, 2),
            "threshold": f">= {float(minimum_execution_probability_pct):.2f}%",
            "status": "BLOCK" if probability_blocked else "PASS",
            "detail": (
                f"{probability:.2f}% is below the Committee minimum."
                if probability_blocked
                else f"{probability:.2f}% satisfies the Committee minimum."
            ),
        },
        {
            "gate": "Expected Value / Expectancy / Expected Win / Expected Loss",
            "authority": "INFORMATIONAL",
            "actual": (
                f"Expectancy={expectancy:.3f}%; "
                f"Expected Win={evaluation.get('expected_win_pct')}; "
                f"Expected Loss={evaluation.get('expected_loss_pct')}"
            ),
            "threshold": "NONE",
            "status": "INFO",
            "detail": "Payoff metrics are retained for research only and cannot approve, reject, rank or size execution.",
        },
        {
            "gate": "Shadow Intelligence",
            "authority": "INFORMATIONAL",
            "actual": str(evaluation.get("shadow_decision") or "WAIT"),
            "threshold": "NONE",
            "status": "INFO",
            "detail": "Shadow adjustment is informational-only and has zero execution authority.",
        },
        {
            "gate": "Expectancy confidence / Historical / Half-Kelly",
            "authority": "INFORMATIONAL",
            "actual": (
                f"Expectancy confidence={evaluation.get('expectancy_confidence_pct')}; "
                f"Historical={evaluation.get('historical_score')}; "
                f"Half-Kelly={evaluation.get('kelly_fraction_pct')}"
            ),
            "threshold": "NONE",
            "status": "INFO",
            "detail": "These values are evidence/research context; they are not Committee blockers.",
        },
    ]

    blocked = [row["gate"] for row in gates if row["status"] == "BLOCK"]
    persisted_eligible = bool(evaluation.get("eligible"))
    calculated_eligible = not blocked
    parity = persisted_eligible == calculated_eligible

    return {
        "candidate_rank": evaluation.get("candidate_rank"),
        "candidate_symbol": evaluation.get("candidate_symbol"),
        "decision": evaluation.get("decision"),
        "persisted_eligible": persisted_eligible,
        "calculated_eligible": calculated_eligible,
        "parity": parity,
        "primary_confidence_pct": evaluation.get("primary_confidence_pct"),
        "execution_probability_pct": probability,
        "expectancy_pct": expectancy,
        "reason": reason,
        "authoritative_blockers": blocked,
        "gates": gates,
    }
