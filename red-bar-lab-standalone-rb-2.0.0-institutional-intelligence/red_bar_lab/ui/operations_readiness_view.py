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


def _field(value: object, name: str, default: object = None) -> object:
    """Read one field from either a mapping or a typed readiness object."""

    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _domain_payload(value: object) -> dict[str, Any]:
    status = str(_field(value, "status", "UNKNOWN") or "UNKNOWN").upper()
    blocking = _field(value, "blocking_reasons", None)
    if blocking is None:
        blocking = _field(value, "reasons", ())
    advisory = _field(value, "advisory_reasons", ())

    blocking_reasons = tuple(str(item) for item in (blocking or ()) if str(item))
    advisory_reasons = tuple(str(item) for item in (advisory or ()) if str(item))

    return {
        "status": status,
        "status_class": _status_class(status),
        "reasons": blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "advisory_reasons": advisory_reasons,
        "primary_reason": blocking_reasons[0] if blocking_reasons else None,
    }


def _yes_no_unknown(value: object) -> str:
    if value is None:
        return "—"
    return "YES" if bool(value) else "NO"


def build_operations_readiness_view_model(
    readiness_gate: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Convert the readiness gate into a stable presentation contract."""

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
        "market_data": _domain_payload(_field(domains_raw, "market_data_readiness")),
        "independent_strategy": _domain_payload(
            _field(domains_raw, "independent_strategy_readiness")
        ),
        "red_bar_v2": _domain_payload(_field(domains_raw, "red_bar_v2_readiness")),
        "execution": _domain_payload(_field(domains_raw, "execution_readiness")),
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
                "Market source": payload.get("market_source") or "—",
                "Market latest candle": payload.get("market_latest_timestamp") or "—",
                "Market rows": payload.get("market_row_count", 0),
                "Market fallback": _yes_no_unknown(payload.get("market_fallback_used")),
                "Market no-lookahead": _yes_no_unknown(
                    payload.get("market_no_lookahead_passed")
                ),
                "Volume": payload.get("volume_status"),
                "Volume source": payload.get("volume_source") or "—",
                "Volume latest candle": payload.get("volume_latest_timestamp") or "—",
                "Volume rows": payload.get("volume_row_count", 0),
                "Volume fallback": _yes_no_unknown(payload.get("volume_fallback_used")),
                "Volume no-lookahead": _yes_no_unknown(
                    payload.get("volume_no_lookahead_passed")
                ),
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
