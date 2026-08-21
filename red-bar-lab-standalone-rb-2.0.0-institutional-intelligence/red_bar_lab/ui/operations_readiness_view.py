from __future__ import annotations

from typing import Any, Mapping


def _status_class(status: object) -> str:
    value = str(status or "UNKNOWN").strip().upper()
    if value in {"READY", "PASS", "AVAILABLE", "HEALTHY"}:
        return "available"
    if value in {"PARTIAL", "WARNING", "AGING"}:
        return "partial"
    if value in {"MISSING", "FAILED", "BLOCKED", "STALE", "ERROR"}:
        return "unavailable"
    return "unknown"


def _domain_payload(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        status = str(value.get("status") or "UNKNOWN").upper()
        reasons = tuple(str(item) for item in value.get("reasons", ()) if str(item))
        return {
            "status": status,
            "status_class": _status_class(status),
            "reasons": reasons,
            "primary_reason": reasons[0] if reasons else None,
        }

    status = str(getattr(value, "status", "UNKNOWN") or "UNKNOWN").upper()
    reasons = tuple(
        str(item)
        for item in (getattr(value, "reasons", ()) or ())
        if str(item)
    )
    return {
        "status": status,
        "status_class": _status_class(status),
        "reasons": reasons,
        "primary_reason": reasons[0] if reasons else None,
    }


def build_operations_readiness_view_model(
    readiness_gate: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Convert the readiness gate into a stable presentation contract.

    This adapter contains no database access and no execution authority. It
    keeps the Operations Centre renderer independent from the gate's internal
    dataclasses and set/tuple representation.
    """

    gate = dict(readiness_gate or {})
    confirmed_ids = tuple(gate.get("confirmed_signal_ids") or ())
    reference_ids = tuple(gate.get("reference_ready_ids") or ())
    market_ids = tuple(gate.get("market_ready_ids") or ())
    volume_ids = tuple(gate.get("volume_ready_ids") or ())
    option_ids = tuple(gate.get("option_ready_ids") or ())
    core_ids = tuple(gate.get("core_signal_ids") or ())
    hybrid_ids = tuple(gate.get("hybrid_signal_ids") or ())

    total = len(confirmed_ids)

    def stage(name: str, ids: tuple[str, ...]) -> dict[str, Any]:
        count = len(ids)
        if total == 0:
            status = "WAITING"
        elif count == total:
            status = "READY"
        elif count > 0:
            status = "PARTIAL"
        else:
            status = "MISSING"
        return {
            "name": name,
            "ready_count": count,
            "missing_count": max(0, total - count),
            "total_count": total,
            "status": status,
            "status_class": _status_class(status),
            "signal_ids": ids,
        }

    domains_raw = gate.get("readiness_domains") or {}
    domains = {
        "market_data": _domain_payload(domains_raw.get("market_data_readiness")),
        "independent_strategy": _domain_payload(
            domains_raw.get("independent_strategy_readiness")
        ),
        "red_bar_v2": _domain_payload(domains_raw.get("red_bar_v2_readiness")),
        "execution": _domain_payload(domains_raw.get("execution_readiness")),
    }

    drilldown = []
    for row in gate.get("drilldown") or ():
        payload = dict(row)
        reasons = payload.get("all_reasons") or ()
        drilldown.append(
            {
                "Signal": payload.get("signal_id"),
                "Confirmed at": payload.get("confirmation_timestamp"),
                "Reference type": payload.get("reference_type"),
                "Reference": payload.get("reference_status"),
                "Reference timestamp": payload.get("reference_timestamp"),
                "Market": payload.get("market_status"),
                "Volume": payload.get("volume_status"),
                "Options": payload.get("option_status"),
                "CORE": "YES" if payload.get("core_eligible") else "NO",
                "HYBRID": "YES" if payload.get("hybrid_eligible") else "NO",
                "Primary reason": payload.get("main_reason") or "—",
                "All reasons": ", ".join(str(item) for item in reasons) or "—",
            }
        )

    return {
        "policy_version": gate.get("policy_version") or "UNKNOWN",
        "authority": gate.get("authority") or "OBSERVATIONAL_ONLY",
        "confirmed_count": total,
        "stages": {
            "reference": stage("NEXT_RED_CANDLE Reference", reference_ids),
            "market": stage("Market Context", market_ids),
            "volume": stage("Volume & Structure", volume_ids),
            "options": stage("Option Context", option_ids),
            "core": stage("CORE", core_ids),
            "hybrid": stage("HYBRID", hybrid_ids),
        },
        "domains": domains,
        "drilldown": tuple(drilldown),
    }


__all__ = ["build_operations_readiness_view_model"]
