from __future__ import annotations

from red_bar_lab.utils import safe_float


def build_performance_gate_trace(selection: dict[str, object], lifecycle: dict[str, object] | None = None) -> dict[str, object]:
    """Explain persisted Performance Selection eligibility without changing it."""
    lifecycle = lifecycle or {}
    reason = str(selection.get("reason") or "")
    upper = reason.upper()
    hard_codes = []
    if "HARD_BLOCK:" in upper:
        hard_text = upper.split("HARD_BLOCK:", 1)[1].split(" | ", 1)[0]
        hard_codes = [item.strip() for item in hard_text.split(",") if item.strip()]
    duplicate = "DUPLICATE_CANDIDATE" in upper or bool(lifecycle.get("duplicate"))

    gates = [
        {"gate": "Spread execution quality", "authority": "HARD", "actual": "BLOCK" if "SPREAD" in hard_codes else "CLEAR", "status": "BLOCK" if "SPREAD" in hard_codes else "PASS", "detail": "Hard blocker only when candidate spread_score <= 0."},
        {"gate": "Liquidity execution quality", "authority": "HARD", "actual": "BLOCK" if "LIQUIDITY" in hard_codes else "CLEAR", "status": "BLOCK" if "LIQUIDITY" in hard_codes else "PASS", "detail": "Hard blocker only when candidate liquidity_score <= 0."},
        {"gate": "Duplicate candidate", "authority": "OPERATIONAL_HARD", "actual": "DUPLICATE" if duplicate else "CLEAR", "status": "BLOCK" if duplicate else "PASS", "detail": "Automation forces selection.eligible=false when an execution already exists for the same signal + account + instrument token."},
        {"gate": "Candidate score", "authority": "SOFT_EVIDENCE", "actual": selection.get("candidate_score"), "status": "INFO", "detail": "Reference evidence only; not a Performance hard blocker."},
        {"gate": "Opportunity score", "authority": "SOFT_EVIDENCE", "actual": selection.get("opportunity_score"), "status": "INFO", "detail": "Opportunity extension eligibility is evidence here; terminal Opportunity rules are handled separately by Committee."},
        {"gate": "Trade Selection Score (TSS)", "authority": "SOFT_EVIDENCE", "actual": selection.get("selection_score"), "threshold": "REFERENCE 70", "status": "INFO", "detail": "TSS below 70 is soft evidence only and does not set selection.eligible=false."},
        {"gate": "Historical performance", "authority": "SOFT_EVIDENCE", "actual": f"samples={selection.get('history_sample_size')}; win={selection.get('history_win_rate_pct')}; PF={selection.get('history_profit_factor')}; expectancy={selection.get('history_expectancy_pct')}", "status": "INFO", "detail": "Historical reference levels are evidence only in the current Performance Selection engine."},
    ]
    blockers = [row["gate"] for row in gates if row["status"] == "BLOCK"]
    return {
        "persisted_eligible": bool(selection.get("eligible")),
        "decision": selection.get("decision"),
        "reason": reason,
        "hard_codes": hard_codes,
        "duplicate": duplicate,
        "blockers": blockers,
        "gates": gates,
        "candidate_symbol": selection.get("candidate_symbol"),
        "candidate_rank": selection.get("candidate_rank"),
        "candidate_score": safe_float(selection.get("candidate_score")),
        "opportunity_score": safe_float(selection.get("opportunity_score")),
        "selection_score": safe_float(selection.get("selection_score")),
        "execution_quality_score": safe_float(selection.get("execution_quality_score")),
        "lifecycle_state": lifecycle.get("state"),
        "lifecycle_reason": lifecycle.get("reason"),
    }
