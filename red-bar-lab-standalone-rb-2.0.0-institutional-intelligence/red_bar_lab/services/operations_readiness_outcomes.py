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
            ("REFERENCE", "reference", reference.get("reason_code"), reference.get("reason")),
            ("MARKET", "market", _stage_reason(drilldown, "MARKET"), None),
            ("VOLUME", "volume", _stage_reason(drilldown, "VOLUME"), None),
            ("OPTIONS", "option", _stage_reason(drilldown, "OPTION"), None),
        )

        for stage, prefix, reason_code, reason in stages:
            status = drilldown.get(f"{prefix}_status")
            normalized_status = str(status or "MISSING").upper()
            source = (
                "reference_levels"
                if stage == "REFERENCE"
                else drilldown.get(f"{prefix}_source")
                or f"{prefix}_context_snapshots"
            )
            latest_timestamp = (
                drilldown.get("reference_timestamp")
                if stage == "REFERENCE"
                else drilldown.get(f"{prefix}_latest_timestamp")
            )
            no_lookahead = (
                reference.get("no_lookahead_passed")
                if stage == "REFERENCE"
                else drilldown.get(f"{prefix}_no_lookahead_passed")
            )
            row = {
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
                "final_retry_status": (
                    "COMPLETE" if normalized_status == "READY" else "PENDING"
                ),
                "operations_policy_version": readiness_gate.get("policy_version"),
                "authority": readiness_gate.get("authority") or "OBSERVATIONAL_ONLY",
            }
            if stage != "REFERENCE":
                row.update(
                    {
                        "fallback_used": bool(
                            drilldown.get(f"{prefix}_fallback_used")
                        ),
                        "row_count": int(
                            drilldown.get(f"{prefix}_row_count") or 0
                        ),
                        "mandatory_present": int(
                            drilldown.get(f"{prefix}_mandatory_present") or 0
                        ),
                        "mandatory_expected": int(
                            drilldown.get(f"{prefix}_mandatory_expected") or 0
                        ),
                        "mandatory_coverage_pct": float(
                            drilldown.get(f"{prefix}_mandatory_coverage_pct") or 0.0
                        ),
                        "optional_present": int(
                            drilldown.get(f"{prefix}_optional_present") or 0
                        ),
                        "optional_expected": int(
                            drilldown.get(f"{prefix}_optional_expected") or 0
                        ),
                        "optional_coverage_pct": float(
                            drilldown.get(f"{prefix}_optional_coverage_pct") or 0.0
                        ),
                        "missing_mandatory_fields": tuple(
                            drilldown.get(f"{prefix}_missing_mandatory_fields") or ()
                        ),
                        "missing_optional_fields": tuple(
                            drilldown.get(f"{prefix}_missing_optional_fields") or ()
                        ),
                    }
                )
            rows.append(row)
    return tuple(rows)


def _stage_reason(drilldown: Mapping[str, Any], prefix: str) -> str | None:
    reasons = tuple(str(value) for value in drilldown.get("all_reasons") or ())
    for reason in reasons:
        if reason.upper().startswith(prefix):
            return reason
    return None


__all__ = ["build_persistent_operations_outcomes"]
