from __future__ import annotations

from typing import Mapping

from red_bar_lab.ui.strategy_risk_readiness import (
    DEFAULT_POLICY,
    RiskReadinessPolicy,
    build_risk_readiness as build_legacy_risk_readiness,
)


SCOPED_RISK_VERSION = "STRATEGY-SCOPED-RISK-V1"


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _strategy_entry(context: Mapping[str, object], strategy_id: str) -> dict[str, object]:
    strategy_risk = _mapping(context.get("strategy_risk"))
    value = strategy_risk.get(strategy_id)
    return dict(value) if isinstance(value, Mapping) else {}


def _scoped_bool(mapping: object, key: str) -> bool | None:
    values = _mapping(mapping)
    if key not in values:
        return None
    value = values.get(key)
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on", "active"}:
        return True
    if text in {"0", "false", "no", "off", "inactive"}:
        return False
    return None


def resolve_candidate_risk_context(
    context: Mapping[str, object] | None,
    candidate: Mapping[str, object],
) -> dict[str, object]:
    """Resolve only the cooldown and risk scopes applicable to one candidate."""
    source = dict(context or {})
    strategy_id = str(candidate.get("strategy_id") or "")
    bundle_id = str(candidate.get("bundle_id") or "")
    contract_key = str(
        candidate.get("instrument_key")
        or candidate.get("instrument_token")
        or candidate.get("trading_symbol")
        or ""
    )

    global_cooldown = source.get("global_cooldown_active")
    if global_cooldown is None:
        global_cooldown = source.get("cooldown_active")
    strategy_cooldown = _scoped_bool(source.get("strategy_cooldowns"), strategy_id)
    bundle_cooldown = _scoped_bool(source.get("bundle_cooldowns"), bundle_id)
    contract_cooldown = _scoped_bool(source.get("contract_cooldowns"), contract_key)

    cooldown_values = [
        value for value in (
            global_cooldown,
            strategy_cooldown,
            bundle_cooldown,
            contract_cooldown,
        )
        if isinstance(value, bool)
    ]
    effective_cooldown = any(cooldown_values) if cooldown_values else None

    strategy = _strategy_entry(source, strategy_id)
    consumed = strategy.get("consumed")
    if consumed is None:
        consumed = strategy.get("risk_consumed")
    if consumed is None and not source.get("strategy_risk"):
        consumed = source.get("strategy_loss_consumed")

    limit = strategy.get("limit")
    if limit is None:
        limit = strategy.get("risk_limit")
    if limit is None and not source.get("strategy_risk"):
        limit = source.get("strategy_loss_limit")

    source.update({
        "cooldown_active": effective_cooldown,
        "strategy_loss_consumed": consumed,
        "strategy_loss_limit": limit,
        "effective_cooldown_scope": {
            "global": global_cooldown,
            "strategy": strategy_cooldown,
            "bundle": bundle_cooldown,
            "contract": contract_cooldown,
        },
        "strategy_risk_scope": {
            "strategy_id": strategy_id,
            "consumed": consumed,
            "limit": limit,
        },
        "scoped_risk_version": SCOPED_RISK_VERSION,
    })
    return source


def build_risk_readiness(
    candidate_result: Mapping[str, object],
    *,
    risk_context: Mapping[str, object] | None = None,
    policy: RiskReadinessPolicy = DEFAULT_POLICY,
) -> dict[str, object]:
    """Evaluate candidates independently with strategy-owned cooldown/risk scopes."""
    rows: list[dict[str, object]] = []
    for raw in candidate_result.get("candidates") or []:
        candidate = dict(raw)
        scoped = resolve_candidate_risk_context(risk_context, candidate)
        result = build_legacy_risk_readiness(
            {"candidates": [candidate]},
            risk_context=scoped,
            policy=policy,
        )
        if not result.get("rows"):
            continue
        row = dict(result["rows"][0])
        row["effective_cooldown_scope"] = scoped.get("effective_cooldown_scope")
        row["strategy_risk_scope"] = scoped.get("strategy_risk_scope")
        row["scoped_risk_version"] = SCOPED_RISK_VERSION
        rows.append(row)

    ready = sum(row.get("risk_outcome") == "RISK_READY_READ_ONLY" for row in rows)
    waiting = sum(row.get("risk_outcome") == "WAIT" for row in rows)
    blocked = sum(row.get("risk_outcome") == "RISK_BLOCKED" for row in rows)
    outcome = (
        "RISK_READY_READ_ONLY" if ready and not waiting and not blocked
        else "RISK_BLOCKED" if blocked
        else "WAIT" if waiting
        else "NOT_ELIGIBLE"
    )
    return {
        "outcome": outcome,
        "policy_version": policy.policy_version,
        "scoped_risk_version": SCOPED_RISK_VERSION,
        "candidates_evaluated": len(rows),
        "risk_ready_count": ready,
        "waiting_count": waiting,
        "blocked_count": blocked,
        "risk_context_available": bool(risk_context),
        "rows": rows,
        "policy_action": "OBSERVE_ONLY",
        "persisted": False,
        "reserved": False,
        "bundle_consumed": False,
        "submitted": False,
    }
