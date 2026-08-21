from __future__ import annotations

from typing import Any, Mapping

from red_bar_lab.services.point_in_time_candle_source import CandleSelectionResult


def build_candle_enrichment_outcome(
    *,
    signal_id: str,
    stage: str,
    selection: CandleSelectionResult | Mapping[str, Any],
    strategy_id: str = "RED_BAR_V2",
    attempt_timestamp: str,
) -> dict[str, Any]:
    payload = selection.as_dict() if isinstance(selection, CandleSelectionResult) else dict(selection)
    status = str(payload.get("status") or "MISSING").upper()
    final_retry_status = "COMPLETE" if status == "READY" else "PENDING"
    return {
        "signal_id": signal_id,
        "strategy_id": strategy_id,
        "stage": stage.upper(),
        "status": status,
        "reason_code": payload.get("reason_code"),
        "reason": payload.get("reason"),
        "input_source": payload.get("selected_source"),
        "input_cutoff_timestamp": payload.get("requested_cutoff"),
        "latest_source_timestamp": payload.get("latest_candle_timestamp"),
        "no_lookahead_passed": payload.get("no_lookahead_passed"),
        "attempt_timestamp": attempt_timestamp,
        "retry_count": 0,
        "final_retry_status": final_retry_status,
        "fallback_used": bool(payload.get("fallback_used")),
        "row_count": int(payload.get("row_count") or 0),
        "candle_source_policy_version": payload.get("policy_version"),
        "authority": "OBSERVATIONAL_ONLY",
    }


__all__ = ["build_candle_enrichment_outcome"]
