from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


def build_persistent_operations_outcomes(
    readiness_gate: Mapping[str, Any],
    *,
    strategy_id: str = "RED_BAR_V2",
    attempt_timestamp: str | None = None,
) -> tuple[dict[str, Any], ...]:
    attempted_at = attempt_timestamp or datetime.now(timezone.utc).isoformat()
    reference_results = readiness_gate.get("reference_results") or {}
    rows: list[dict[str, Any]] = []

    for drilldown in readiness_gate.get("drilldown") or ():
        signal_id = str(drilldown.get("signal_id") or "").strip()
        if not signal_id:
            continue
        cutoff = drilldown.get("confirmation_timestamp")
        reference = reference_results.get(signal_id) or {}
        stages = (
            (
                "REFERENCE",
                drilldown.get("reference_status"),
                reference.get("reason_code"),
                reference.get("reason"),
                "reference_levels",
                drilldown.get("reference_timestamp"),
                reference.get("no_lookahead_passed"),
            ),
            (
                "MARKET",
                drilldown.get("market_status"),
                _stage_reason(drilldown, "MARKET"),
                None,
                "market_context_snapshots",
                None,
                None,
            ),
            (
                "VOLUME",
                drilldown.get("volume_status"),
                _stage_reason(drilldown, "VOLUME"),
                None,
                "volume_structure_snapshots",
                None,
                None,
            ),
            (
                "OPTIONS",
                drilldown.get("option_status"),
                _stage_reason(drilldown, "OPTION"),
                None,
                "option_context_snapshots",
                None,
                None,
            ),
        )
        for stage, status, reason_code, reason, source, latest_timestamp, no_lookahead in stages:
            normalized_status = str(status or "MISSING").upper()
            rows.append(
                {
                    "signal_id": signal_id,
                    "strategy_id": strategy_id,
                    "stage": stage,
                    "status": normalized_status,
                    "reason_code": reason_code,
                    "reason": reason,
                    "input_source": source,
                    "input_cutoff_timestamp": cutoff,
                    "latest_source_timestamp": latest_timestamp,
                    "no_lookahead_passed": no_lookahead,
                    "attempt_timestamp": attempted_at,
                    "retry_count": 0,
                    "final_retry_status": "COMPLETE" if normalized_status == "READY" else "PENDING",
                    "operations_policy_version": readiness_gate.get("policy_version"),
                    "authority": readiness_gate.get("authority") or "OBSERVATIONAL_ONLY",
                }
            )
    return tuple(rows)


def _stage_reason(drilldown: Mapping[str, Any], prefix: str) -> str | None:
    reasons = tuple(str(value) for value in drilldown.get("all_reasons") or ())
    for reason in reasons:
        if reason.upper().startswith(prefix):
            return reason
    return None


__all__ = ["build_persistent_operations_outcomes"]
