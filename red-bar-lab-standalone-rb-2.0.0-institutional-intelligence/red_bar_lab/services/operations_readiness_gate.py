from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable, Mapping

from red_bar_lab.services.feature_store_readiness import calculate_feature_store_readiness
from red_bar_lab.services.readiness_domains import build_readiness_domains
from red_bar_lab.services.red_bar_v2_reference_readiness import (
    RED_BAR_V2_REFERENCE_TYPE,
    assess_red_bar_v2_reference_readiness,
)

OPERATIONS_READINESS_POLICY_VERSION = "operations-readiness-gate-v2"


def _ids(rows: Iterable[Mapping[str, Any]], *, ready_field: str = "status") -> set[str]:
    result: set[str] = set()
    for row in rows:
        signal_id = str(row.get("signal_id") or "").strip()
        status = str(row.get(ready_field) or "").strip().upper()
        if signal_id and status in {"READY", "PASS", "AVAILABLE", "TRUE", "1"}:
            result.add(signal_id)
    return result


def build_operations_readiness_gate(
    *,
    confirmed_signals: Iterable[Mapping[str, Any]],
    references_by_signal: Mapping[str, Mapping[str, Any]],
    market_outcomes: Iterable[Mapping[str, Any]],
    volume_outcomes: Iterable[Mapping[str, Any]],
    option_outcomes: Iterable[Mapping[str, Any]],
    market_data_blockers: Iterable[str] = (),
    independent_strategy_blockers: Iterable[str] = (),
    execution_blockers: Iterable[str] = ("EXECUTION_POLICY_NOT_APPROVED",),
) -> dict[str, Any]:
    """Build one observational readiness result for the Operations Centre.

    The function keeps exact signal IDs throughout the calculation. It does not
    grant execution authority and does not mutate strategy decisions.
    """

    signals = [dict(row) for row in confirmed_signals]
    confirmed_ids = {
        str(row.get("signal_id") or "").strip()
        for row in signals
        if str(row.get("signal_id") or "").strip()
    }

    reference_results: dict[str, dict[str, Any]] = {}
    reference_ready_ids: set[str] = set()
    for signal in signals:
        signal_id = str(signal.get("signal_id") or "").strip()
        result = assess_red_bar_v2_reference_readiness(
            signal,
            references_by_signal.get(signal_id),
        )
        payload = asdict(result)
        reference_results[signal_id] = payload
        if result.status == "READY":
            reference_ready_ids.add(signal_id)

    market_ready_ids = _ids(market_outcomes)
    volume_ready_ids = _ids(volume_outcomes)
    option_ready_ids = _ids(option_outcomes)

    feature_readiness = calculate_feature_store_readiness(
        confirmed_signal_ids=confirmed_ids,
        market_ready_ids=market_ready_ids,
        volume_ready_ids=volume_ready_ids,
        option_ready_ids=option_ready_ids,
    )

    rbv2_blockers = [
        f"{signal_id}:{payload['reason_code']}"
        for signal_id, payload in reference_results.items()
        if payload.get("status") != "READY"
    ]
    readiness_domains = build_readiness_domains(
        market_data_blockers=tuple(market_data_blockers),
        independent_strategy_blockers=tuple(independent_strategy_blockers),
        red_bar_v2_blockers=tuple(rbv2_blockers),
        execution_blockers=tuple(execution_blockers),
    )

    market_by_id = {str(row.get("signal_id") or "").strip(): dict(row) for row in market_outcomes}
    volume_by_id = {str(row.get("signal_id") or "").strip(): dict(row) for row in volume_outcomes}
    option_by_id = {str(row.get("signal_id") or "").strip(): dict(row) for row in option_outcomes}

    drilldown: list[dict[str, Any]] = []
    for signal in signals:
        signal_id = str(signal.get("signal_id") or "").strip()
        reference = reference_results[signal_id]
        market = market_by_id.get(signal_id, {})
        volume = volume_by_id.get(signal_id, {})
        option = option_by_id.get(signal_id, {})

        reasons = []
        for payload in (reference, market, volume, option):
            code = str(payload.get("reason_code") or "").strip()
            if code:
                reasons.append(code)

        drilldown.append(
            {
                "signal_id": signal_id,
                "confirmation_timestamp": signal.get("confirmation_timestamp")
                or signal.get("confirmed_at")
                or signal.get("signal_timestamp"),
                "reference_type": reference.get("reference_type") or RED_BAR_V2_REFERENCE_TYPE,
                "reference_status": reference.get("status"),
                "reference_timestamp": reference.get("reference_timestamp"),
                "market_status": str(market.get("status") or "MISSING").upper(),
                "volume_status": str(volume.get("status") or "MISSING").upper(),
                "option_status": str(option.get("status") or "MISSING").upper(),
                "core_eligible": signal_id in set(feature_readiness.core_signal_ids),
                "hybrid_eligible": signal_id in set(feature_readiness.hybrid_signal_ids),
                "main_reason": reasons[0] if reasons else None,
                "all_reasons": tuple(reasons),
            }
        )

    return {
        "policy_version": OPERATIONS_READINESS_POLICY_VERSION,
        "authority": "OBSERVATIONAL_ONLY",
        "confirmed_signal_ids": tuple(sorted(confirmed_ids)),
        "reference_ready_ids": tuple(sorted(reference_ready_ids)),
        "market_ready_ids": tuple(sorted(market_ready_ids & confirmed_ids)),
        "volume_ready_ids": tuple(sorted(volume_ready_ids & confirmed_ids)),
        "option_ready_ids": tuple(sorted(option_ready_ids & confirmed_ids)),
        "core_signal_ids": tuple(feature_readiness.core_signal_ids),
        "hybrid_signal_ids": tuple(feature_readiness.hybrid_signal_ids),
        "reference_results": reference_results,
        "readiness_domains": readiness_domains,
        "drilldown": tuple(drilldown),
    }


__all__ = [
    "OPERATIONS_READINESS_POLICY_VERSION",
    "build_operations_readiness_gate",
]
