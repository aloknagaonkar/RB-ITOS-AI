from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import median
from typing import Mapping, Sequence

import streamlit as st


SOURCE_VERSION = "OPPORTUNITY-CONTEXT-SOURCE-V2"


@dataclass(frozen=True)
class OpportunityInputPolicy:
    policy_version: str = "OPPORTUNITY-INPUT-POLICY-V1"
    premium_risk_fraction: float = 0.25
    minimum_spread_multiple: float = 2.0
    minimum_tick_multiple: float = 4.0
    favourable_excursion_r_multiple: float = 2.5
    adverse_excursion_r_multiple: float = 1.0
    charge_fraction_per_unit: float = 0.001
    minimum_charge_per_unit: float = 0.02


DEFAULT_INPUT_POLICY = OpportunityInputPolicy()


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) or math.isinf(result) else result


def _first(row: Mapping[str, object], *names: str) -> object:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _text(value: object) -> str:
    return str(value or "").strip().upper()


def _historical_excursions(
    candidate: Mapping[str, object],
    records: Sequence[Mapping[str, object]],
) -> tuple[float | None, float | None, int]:
    strategy_id = _text(candidate.get("strategy_id"))
    side = _text(candidate.get("contract_side") or candidate.get("requested_side"))
    mfe_values: list[float] = []
    mae_values: list[float] = []
    matched = 0
    for raw in records:
        row = dict(raw)
        if _text(row.get("strategy_id")) != strategy_id:
            continue
        row_side = _text(row.get("contract_side") or row.get("side"))
        if side and row_side and row_side != side:
            continue
        matched += 1
        mfe = _number(_first(row, "mfe_points", "maximum_favourable_excursion"))
        mae = _number(_first(row, "mae_points", "maximum_adverse_excursion"))
        if mfe is not None:
            mfe_values.append(mfe)
        if mae is not None:
            mae_values.append(abs(mae))
    return (
        median(mfe_values) if mfe_values else None,
        median(mae_values) if mae_values else None,
        matched,
    )


def _explicit_candidate_context(
    explicit: Mapping[str, object], candidate_id: str
) -> dict[str, object]:
    result = dict(explicit)
    nested = explicit.get("candidates")
    if isinstance(nested, Mapping) and isinstance(nested.get(candidate_id), Mapping):
        result.update(dict(nested[candidate_id]))
    return result


def _round_to_tick(value: float, tick: float | None) -> float:
    if tick is None or tick <= 0:
        return round(value, 4)
    return round(round(value / tick) * tick, 4)


def _policy_inputs(
    candidate: Mapping[str, object],
    *,
    entry: float | None,
    bid: float | None,
    ask: float | None,
    policy: OpportunityInputPolicy,
) -> dict[str, float | None]:
    """Build conservative research inputs; never grants execution authority."""
    if entry is None or entry <= 0:
        return {"stop": None, "charges": None, "mfe": None, "mae": None, "risk": None}
    tick = _number(candidate.get("tick_size"))
    spread = max(0.0, ask - bid) if ask is not None and bid is not None else 0.0
    risk = max(
        entry * policy.premium_risk_fraction,
        spread * policy.minimum_spread_multiple,
        (tick or 0.0) * policy.minimum_tick_multiple,
    )
    risk = min(risk, entry * 0.80)
    stop = _round_to_tick(max(tick or 0.01, entry - risk), tick)
    actual_risk = max(0.0, entry - stop)
    charges = max(policy.minimum_charge_per_unit, entry * policy.charge_fraction_per_unit)
    return {
        "stop": stop if 0 < stop < entry else None,
        "charges": round(charges, 4),
        "mfe": round(actual_risk * policy.favourable_excursion_r_multiple, 4),
        "mae": round(actual_risk * policy.adverse_excursion_r_multiple, 4),
        "risk": round(actual_risk, 4),
    }


def build_opportunity_context(
    candidate_result: Mapping[str, object],
    *,
    historical_records: Sequence[Mapping[str, object]] | None = None,
    account_context: Mapping[str, object] | None = None,
    explicit_context: Mapping[str, object] | None = None,
    input_policy: OpportunityInputPolicy = DEFAULT_INPUT_POLICY,
) -> dict[str, object]:
    """Build candidate-scoped, provenance-labelled, read-only opportunity inputs."""
    records = [dict(row) for row in (historical_records or [])]
    account = dict(account_context or {})
    explicit = dict(explicit_context or {})
    available_cash = _number(account.get("available_cash"))
    reserved_capital = _number(account.get("reserved_capital")) or 0.0
    available_capital = available_cash - reserved_capital if available_cash is not None else None
    account_lots = _number(account.get("proposed_lots"))
    account_charge = _number(_first(account, "estimated_charges_per_unit", "option_charges_per_unit"))

    candidates: dict[str, dict[str, object]] = {}
    provenance: dict[str, dict[str, dict[str, object]]] = {}

    for raw in candidate_result.get("candidates") or []:
        candidate = dict(raw)
        cid = str(candidate.get("candidate_id") or "Unavailable")
        supplied = _explicit_candidate_context(explicit, cid)
        opportunity = candidate.get("opportunity")
        embedded = dict(opportunity) if isinstance(opportunity, Mapping) else {}
        field_sources: dict[str, dict[str, object]] = {}

        def resolve(name: str, aliases: tuple[str, ...], *, derived: object = None, derived_source: str = "") -> object:
            value = _first(supplied, name, *aliases)
            source = "EXPLICIT_CALLER_OVERRIDE"
            if value in (None, ""):
                value = _first(candidate, name, *aliases)
                source = "CANDIDATE"
            if value in (None, ""):
                value = _first(embedded, name, *aliases)
                source = "CANDIDATE_EMBEDDED_OPPORTUNITY"
            if value in (None, "") and derived not in (None, ""):
                value = derived
                source = derived_source
            authoritative = source in {
                "EXPLICIT_CALLER_OVERRIDE", "CANDIDATE",
                "CANDIDATE_EMBEDDED_OPPORTUNITY", "ACCOUNT_CONTEXT",
                "HISTORICAL_STRATEGY_SIDE_MEDIAN",
            } or source.startswith("APPROVED_READ_ONLY_POLICY:")
            field_sources[name] = {
                "value": value,
                "source": source if value not in (None, "") else "UNAVAILABLE",
                "authoritative": authoritative,
            }
            return value

        entry = _number(_first(candidate, "ltp", "entry_premium"))
        bid = _number(candidate.get("bid"))
        ask = _number(candidate.get("ask"))
        quote_slippage = max(0.0, ask - entry) if ask is not None and entry is not None else None
        historical_mfe, historical_mae, historical_samples = _historical_excursions(candidate, records)
        policy_values = _policy_inputs(candidate, entry=entry, bid=bid, ask=ask, policy=input_policy)
        policy_source = f"APPROVED_READ_ONLY_POLICY:{input_policy.policy_version}"

        stop = resolve(
            "initial_option_stop",
            ("initial_stop", "stop_price", "stop_loss_price", "stop_loss"),
            derived=policy_values["stop"],
            derived_source=policy_source,
        )
        slippage = resolve(
            "estimated_slippage", ("slippage", "slippage_per_unit"),
            derived=quote_slippage, derived_source="QUOTE_DERIVED_BUY_IMPACT",
        )
        charges = resolve(
            "estimated_charges", ("charges", "charges_per_unit", "estimated_costs_per_unit"),
            derived=account_charge if account_charge is not None else policy_values["charges"],
            derived_source="ACCOUNT_CONTEXT" if account_charge is not None else policy_source,
        )
        mfe = resolve(
            "expected_favourable_excursion", ("expected_mfe", "mfe_points"),
            derived=historical_mfe if historical_mfe is not None else policy_values["mfe"],
            derived_source="HISTORICAL_STRATEGY_SIDE_MEDIAN" if historical_mfe is not None else policy_source,
        )
        mae = resolve(
            "expected_adverse_excursion", ("expected_mae", "mae_points"),
            derived=historical_mae if historical_mae is not None else policy_values["mae"],
            derived_source="HISTORICAL_STRATEGY_SIDE_MEDIAN" if historical_mae is not None else policy_source,
        )
        capital = resolve(
            "available_capital", ("available_cash",),
            derived=available_capital, derived_source="ACCOUNT_CONTEXT",
        )
        lots = resolve(
            "proposed_lots", ("lots",),
            derived=account_lots, derived_source="ACCOUNT_CONTEXT",
        )

        candidates[cid] = {
            "entry_premium": entry,
            "bid": bid,
            "ask": ask,
            "spread_pct": candidate.get("spread_pct"),
            "initial_option_stop": _number(stop),
            "estimated_slippage": _number(slippage),
            "estimated_charges": _number(charges),
            "expected_favourable_excursion": _number(mfe),
            "expected_adverse_excursion": _number(mae),
            "available_capital": _number(capital),
            "proposed_lots": int(_number(lots)) if _number(lots) is not None else None,
            "historical_excursion_sample_count": historical_samples,
            "opportunity_input_policy_version": input_policy.policy_version,
            "policy_initial_risk_points": policy_values["risk"],
            "opportunity_context_source_version": SOURCE_VERSION,
            "source_read_only": True,
        }
        provenance[cid] = field_sources

    top_level = {key: value for key, value in explicit.items() if key not in {"candidates", "field_provenance"}}
    return {
        **top_level,
        "candidates": candidates,
        "field_provenance": provenance,
        "source_version": SOURCE_VERSION,
        "input_policy_version": input_policy.policy_version,
        "source_read_only": True,
        "persisted": False,
        "reserved": False,
        "submitted": False,
    }


def render_opportunity_context_source(context: Mapping[str, object]) -> None:
    st.markdown("#### 7A.1 Opportunity Input Sources")
    st.caption(
        "Explicit and historical inputs take priority. Missing stop, cost and excursion inputs may use the approved read-only research policy; every source is labelled and no execution authority is granted."
    )
    rows = []
    for candidate_id, fields in (context.get("field_provenance") or {}).items():
        if not isinstance(fields, Mapping):
            continue
        for field, detail in fields.items():
            if isinstance(detail, Mapping):
                rows.append({
                    "candidate_id": candidate_id,
                    "field": field,
                    "value": detail.get("value"),
                    "source": detail.get("source"),
                    "authoritative": detail.get("authoritative"),
                })
    if rows:
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.info("No Section 7 opportunity input provenance is available.")


__all__ = [
    "SOURCE_VERSION", "OpportunityInputPolicy", "DEFAULT_INPUT_POLICY",
    "build_opportunity_context", "render_opportunity_context_source",
]
