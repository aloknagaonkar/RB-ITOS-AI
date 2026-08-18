from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import hashlib
import math
from typing import Mapping

import streamlit as st


ORDER_SPEC_VERSION = "ORDER-SPECIFICATION-V1"


@dataclass(frozen=True)
class OrderSpecificationPolicy:
    policy_version: str = ORDER_SPEC_VERSION
    transaction_intent: str = "BUY_TO_OPEN"
    order_type: str = "LIMIT"
    time_in_force: str = "DAY"
    price_source: str = "ASK_THEN_LTP"
    require_whole_lots: bool = True
    require_protective_stop: bool = True


DEFAULT_POLICY = OrderSpecificationPolicy()


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) or math.isinf(result) else result


def _present(value: object) -> bool:
    return value not in (None, "", "Unavailable", "UNAVAILABLE", "Not created")


def _tick_round(value: float | None, tick: float | None, *, upward: bool) -> float | None:
    if value is None or tick is None or value <= 0 or tick <= 0:
        return None
    try:
        raw = Decimal(str(value))
        step = Decimal(str(tick))
        units = (raw / step).to_integral_value(rounding=ROUND_CEILING if upward else ROUND_FLOOR)
        return float(units * step)
    except (InvalidOperation, ValueError, ZeroDivisionError):
        return None


def _specification_id(row: Mapping[str, object]) -> str:
    raw = "|".join(str(row.get(name) or "") for name in (
        "committee_id", "strategy_id", "bundle_id", "signal_id", "candidate_id",
        "exchange", "instrument_token", "instrument_key", "trading_symbol",
        "quantity", "admission_priority_rank",
    ))
    return f"ORDSPEC-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20].upper()}"


def build_order_specification(
    committee_result: Mapping[str, object],
    *,
    policy: OrderSpecificationPolicy = DEFAULT_POLICY,
) -> dict[str, object]:
    """Create broker-neutral read-only order intents from committee-ready candidates."""
    rows: list[dict[str, object]] = []
    for raw in committee_result.get("rows") or []:
        row = dict(raw)
        waits: list[str] = []
        checks: list[dict[str, object]] = []

        def check(name: str, passed: bool, detail: str) -> None:
            checks.append({"check": name, "status": "PASS" if passed else "WAIT", "detail": detail})
            if not passed:
                waits.append(detail)

        committee_ready = (
            str(row.get("committee_outcome") or "") == "COMMITTEE_READY_READ_ONLY"
            and row.get("order_preparation_allowed") is True
        )
        check("Committee authority", committee_ready, "COMMITTEE_NOT_READY")

        identity_ok = all(_present(row.get(name)) for name in (
            "strategy_id", "bundle_id", "signal_id", "candidate_id", "role",
            "exchange", "trading_symbol", "expiry", "strike",
        )) and (_present(row.get("instrument_token")) or _present(row.get("instrument_key")))
        check("Order identity", identity_ok, "ORDER_IDENTITY_INCOMPLETE")

        quantity = _number(row.get("quantity"))
        lot_size = _number(row.get("lot_size"))
        quantity_integer = quantity is not None and quantity > 0 and float(quantity).is_integer()
        lot_integer = lot_size is not None and lot_size > 0 and float(lot_size).is_integer()
        whole_lots = (
            quantity_integer and lot_integer and int(quantity) % int(lot_size) == 0
            if policy.require_whole_lots else quantity_integer
        )
        check("Quantity and lot alignment", bool(whole_lots), "QUANTITY_NOT_WHOLE_LOT_ALIGNED")

        tick_size = _number(row.get("tick_size"))
        tick_ok = tick_size is not None and tick_size > 0
        check("Tick size", tick_ok, "INVALID_OR_MISSING_TICK_SIZE")

        opportunity = dict(row.get("opportunity") or {})
        ask = _number(row.get("ask"))
        ltp = _number(row.get("ltp") if row.get("ltp") is not None else opportunity.get("entry_premium"))
        reference_price = ask if ask is not None and ask > 0 else ltp
        price_source = "ASK" if ask is not None and ask > 0 else "LTP" if ltp is not None and ltp > 0 else "UNAVAILABLE"
        limit_price = _tick_round(reference_price, tick_size, upward=True)
        price_ok = reference_price is not None and reference_price > 0 and limit_price is not None
        check("Limit-price construction", price_ok, "LIMIT_PRICE_UNAVAILABLE")

        raw_stop = _number(opportunity.get("initial_option_stop"))
        stop_trigger = _tick_round(raw_stop, tick_size, upward=False)
        stop_ok = stop_trigger is not None and limit_price is not None and 0 < stop_trigger < limit_price
        if policy.require_protective_stop:
            check("Protective-stop construction", stop_ok, "PROTECTIVE_STOP_INVALID_OR_UNAVAILABLE")

        required_capital = _number(row.get("required_capital"))
        proposed_risk = _number(row.get("total_proposed_risk"))
        economics_ok = required_capital is not None and required_capital > 0 and proposed_risk is not None and proposed_risk > 0
        check("Approved economics", economics_ok, "APPROVED_CAPITAL_OR_RISK_UNAVAILABLE")

        outcome = "ORDER_SPEC_READY_READ_ONLY" if not waits else "WAIT"
        lots = int(quantity / lot_size) if whole_lots and quantity is not None and lot_size is not None else None
        rows.append({
            **row,
            "order_specification_id": _specification_id(row),
            "order_specification_outcome": outcome,
            "order_specification_reason": ", ".join(waits) if waits else "BROKER_NEUTRAL_ORDER_SPECIFICATION_COMPLETE",
            "order_specification_checks": checks,
            "order_specification_version": policy.policy_version,
            "transaction_intent": policy.transaction_intent,
            "order_type": policy.order_type,
            "time_in_force": policy.time_in_force,
            "price_source_policy": policy.price_source,
            "reference_price_source": price_source,
            "reference_price": reference_price,
            "limit_price": limit_price,
            "protective_stop_trigger": stop_trigger,
            "order_quantity": int(quantity) if quantity_integer else None,
            "order_lots": lots,
            "order_prepared_read_only": outcome == "ORDER_SPEC_READY_READ_ONLY",
            "broker_payload_created": False,
            "order_created": False,
            "order_submitted": False,
            "persisted": False,
            "reserved": False,
            "bundle_consumed": False,
            "submitted": False,
            "policy_action": "OBSERVE_ONLY",
            "next_step": (
                "Section 9C may translate this specification into a disabled broker payload preview."
                if outcome == "ORDER_SPEC_READY_READ_ONLY"
                else "Resolve the exact order-specification wait reason."
            ),
        })

    ready = sum(row["order_specification_outcome"] == "ORDER_SPEC_READY_READ_ONLY" for row in rows)
    waiting = sum(row["order_specification_outcome"] == "WAIT" for row in rows)
    return {
        "outcome": "ORDER_SPEC_READY_READ_ONLY" if ready else "WAIT" if waiting else "NOT_ELIGIBLE",
        "rows": rows,
        "ready_count": ready,
        "waiting_count": waiting,
        "order_specification_version": policy.policy_version,
        "policy_action": "OBSERVE_ONLY",
        "broker_payload_created": False,
        "order_created": False,
        "order_submitted": False,
        "persisted": False,
        "reserved": False,
        "bundle_consumed": False,
        "submitted": False,
    }


def render_order_specification(result: Mapping[str, object]) -> None:
    st.markdown("#### 9B. Read-Only Broker-Neutral Order Specification")
    st.caption(
        "Builds a deterministic order intent from committee-ready candidates. No broker payload, "
        "database record, reservation, bundle consumption or order submission is created."
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Outcome", str(result.get("outcome") or "NOT_ELIGIBLE"))
    c2.metric("Ready", int(result.get("ready_count") or 0))
    c3.metric("Waiting", int(result.get("waiting_count") or 0))
    rows = [dict(row) for row in result.get("rows") or []]
    if not rows:
        st.info("No Section 9A candidate is available for order specification.")
        return
    st.dataframe([
        {key: row.get(key) for key in (
            "order_specification_id", "candidate_id", "strategy_id", "role",
            "exchange", "trading_symbol", "transaction_intent", "order_type",
            "time_in_force", "order_lots", "order_quantity", "reference_price_source",
            "reference_price", "limit_price", "protective_stop_trigger",
            "required_capital", "total_proposed_risk", "order_specification_outcome",
            "order_specification_reason",
        )}
        for row in rows
    ], width="stretch", hide_index=True)
    for row in rows:
        with st.expander(f"How was the order specification built for {row.get('candidate_id')}?"):
            st.dataframe(list(row.get("order_specification_checks") or []), width="stretch", hide_index=True)
            st.write(f"**Outcome:** {row.get('order_specification_outcome')}")
            st.write(f"**Exact reason:** {row.get('order_specification_reason')}")
            st.write(f"**Next step:** {row.get('next_step')}")
            st.write("**Safety:** No broker payload or order was created or submitted.")


__all__ = [
    "OrderSpecificationPolicy",
    "DEFAULT_POLICY",
    "ORDER_SPEC_VERSION",
    "build_order_specification",
    "render_order_specification",
]
