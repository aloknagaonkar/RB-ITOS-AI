from __future__ import annotations

import math
from typing import Mapping


EXPOSURE_MODEL_VERSION = "MONETARY-EXPOSURE-V1"


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(result) or math.isinf(result) else result


def canonical_contract_identity(row: Mapping[str, object]) -> dict[str, object]:
    """Return a canonical contract key and the confidence of the identity source."""
    exchange = str(row.get("exchange") or row.get("exchange_segment") or "").strip().upper()
    token = str(row.get("instrument_token") or row.get("security_id") or "").strip()
    instrument_key = str(row.get("instrument_key") or "").strip()
    symbol = str(row.get("trading_symbol") or row.get("tradingsymbol") or row.get("symbol") or "").strip()
    if exchange and token:
        return {"key": f"{exchange}|TOKEN|{token}", "confidence": "VERIFIED_EXCHANGE_TOKEN"}
    if exchange and instrument_key:
        return {"key": f"{exchange}|KEY|{instrument_key}", "confidence": "VERIFIED_EXCHANGE_KEY"}
    if token:
        return {"key": f"TOKEN|{token}", "confidence": "TOKEN_WITHOUT_EXCHANGE"}
    if instrument_key:
        return {"key": f"KEY|{instrument_key}", "confidence": "KEY_WITHOUT_EXCHANGE"}
    if symbol:
        return {"key": f"SYMBOL|{symbol}", "confidence": "FALLBACK_SYMBOL"}
    return {"key": "", "confidence": "UNAVAILABLE"}


def _capital(row: Mapping[str, object]) -> float | None:
    direct = _number(row.get("required_capital"))
    if direct is not None:
        return abs(direct)
    quantity = _number(row.get("quantity"))
    if quantity is None:
        lot_size = _number(row.get("lot_size"))
        lots = _number(row.get("proposed_lots")) or 1.0
        quantity = lot_size * lots if lot_size is not None else None
    price = _number(row.get("ltp"))
    opportunity = row.get("opportunity") if isinstance(row.get("opportunity"), Mapping) else {}
    if price is None:
        price = _number(opportunity.get("entry_premium"))
    return abs(price * quantity) if price is not None and quantity is not None else None


def _risk(row: Mapping[str, object]) -> float | None:
    direct = _number(row.get("total_proposed_risk"))
    if direct is not None:
        return abs(direct)
    opportunity = row.get("opportunity") if isinstance(row.get("opportunity"), Mapping) else {}
    entry = _number(row.get("ltp"))
    if entry is None:
        entry = _number(opportunity.get("entry_premium"))
    stop = _number(opportunity.get("initial_option_stop"))
    slippage = _number(opportunity.get("estimated_slippage"))
    charges = _number(opportunity.get("estimated_charges"))
    lot_size = _number(row.get("lot_size"))
    lots = _number(row.get("proposed_lots")) or 1.0
    quantity = lot_size * lots if lot_size is not None else None
    if None in (entry, stop, slippage, charges, quantity):
        return None
    return abs((entry - stop + slippage + charges) * quantity)


def _side(row: Mapping[str, object]) -> str:
    return str(row.get("contract_side") or row.get("option_side") or row.get("side") or "").upper()


def _expiry(row: Mapping[str, object]) -> str:
    return str(row.get("expiry") or row.get("expiry_date") or "")


def _strike_key(row: Mapping[str, object]) -> str:
    strike = _number(row.get("strike") if row.get("strike") is not None else row.get("strike_price"))
    expiry = _expiry(row)
    side = _side(row)
    return f"{expiry}|{strike}|{side}" if strike is not None and expiry and side else ""


def _add(total: dict[str, float], key: str, value: float | None) -> None:
    if key and value is not None:
        total[key] = total.get(key, 0.0) + abs(value)


def _existing_totals(context: Mapping[str, object]) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, float], dict[str, int], set[str]]:
    side_capital: dict[str, float] = {}
    side_risk: dict[str, float] = {}
    expiry_capital: dict[str, float] = {}
    expiry_risk: dict[str, float] = {}
    strike_counts: dict[str, int] = {}
    identities: set[str] = set()
    positions = [dict(row) for row in context.get("active_positions") or [] if isinstance(row, Mapping)]
    positions += [dict(row) for row in context.get("admitted_candidates") or [] if isinstance(row, Mapping)]
    for row in positions:
        identity = canonical_contract_identity(row)["key"]
        if identity:
            identities.add(str(identity))
        capital = _number(row.get("exposure"))
        if capital is None:
            capital = _capital(row)
        risk = _number(row.get("total_risk") or row.get("risk") or row.get("initial_risk"))
        _add(side_capital, _side(row), capital)
        _add(side_risk, _side(row), risk)
        _add(expiry_capital, _expiry(row), capital)
        _add(expiry_risk, _expiry(row), risk)
        strike_key = _strike_key(row)
        if strike_key:
            strike_counts[strike_key] = strike_counts.get(strike_key, 0) + 1
    return side_capital, side_risk, expiry_capital, expiry_risk, strike_counts, identities


def apply_monetary_exposure_admission(
    portfolio_result: Mapping[str, object],
    *,
    account_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Add cumulative monetary exposure controls without mutating strategy signals."""
    context = dict(account_context or {})
    side_capital, side_risk, expiry_capital, expiry_risk, strike_counts, existing_ids = _existing_totals(context)
    proposed_ids: set[str] = set()
    rows: list[dict[str, object]] = []

    max_side_capital = {
        "CE": _number(context.get("maximum_ce_capital_exposure")),
        "PE": _number(context.get("maximum_pe_capital_exposure")),
    }
    max_side_risk = {
        "CE": _number(context.get("maximum_ce_risk_exposure")),
        "PE": _number(context.get("maximum_pe_risk_exposure")),
    }
    max_expiry_capital = _number(context.get("maximum_expiry_capital_exposure"))
    max_expiry_risk = _number(context.get("maximum_expiry_risk_exposure"))
    max_same_strike = _number(context.get("maximum_same_strike_positions"))

    for raw in portfolio_result.get("rows") or []:
        row = dict(raw)
        checks = list(row.get("checks") or [])
        waits: list[str] = []
        rejects: list[str] = []
        identity = canonical_contract_identity(row)
        key = str(identity["key"])
        capital = _capital(row)
        risk = _risk(row)
        side = _side(row)
        expiry = _expiry(row)
        strike_key = _strike_key(row)

        if key and key in existing_ids:
            rejects.append("REJECT_DUPLICATE_EXPOSURE")
            checks.append({"check": "Canonical contract exposure", "status": "REJECT", "detail": f"{key}; {identity['confidence']}; already active/admitted"})
        elif key and key in proposed_ids:
            waits.append("WAIT_PORTFOLIO_CONFLICT")
            checks.append({"check": "Canonical contract exposure", "status": "WAIT", "detail": f"{key}; {identity['confidence']}; already proposed"})
        else:
            checks.append({"check": "Canonical contract exposure", "status": "PASS" if key else "INFO", "detail": f"{key or 'UNAVAILABLE'}; {identity['confidence']}"})

        projected_side_capital = side_capital.get(side, 0.0) + (capital or 0.0) if side else None
        projected_side_risk = side_risk.get(side, 0.0) + (risk or 0.0) if side else None
        projected_expiry_capital = expiry_capital.get(expiry, 0.0) + (capital or 0.0) if expiry else None
        projected_expiry_risk = expiry_risk.get(expiry, 0.0) + (risk or 0.0) if expiry else None
        projected_strike_count = strike_counts.get(strike_key, 0) + 1 if strike_key else None

        def limit_check(name: str, projected: float | None, limit: float | None, reason: str) -> None:
            if projected is None:
                checks.append({"check": name, "status": "INFO", "detail": "INPUT_UNAVAILABLE"})
            elif limit is None:
                checks.append({"check": name, "status": "INFO", "detail": f"projected={projected:.2f}; limit=NOT_CONFIGURED"})
            elif projected > limit:
                waits.append(reason)
                checks.append({"check": name, "status": "WAIT", "detail": f"projected={projected:.2f}; limit={limit:.2f}"})
            else:
                checks.append({"check": name, "status": "PASS", "detail": f"projected={projected:.2f}; limit={limit:.2f}"})

        limit_check(f"{side or 'Unknown'} capital exposure", projected_side_capital, max_side_capital.get(side), "WAIT_DIRECTIONAL_CAPITAL_CONCENTRATION")
        limit_check(f"{side or 'Unknown'} risk exposure", projected_side_risk, max_side_risk.get(side), "WAIT_DIRECTIONAL_RISK_CONCENTRATION")
        limit_check("Expiry capital exposure", projected_expiry_capital, max_expiry_capital, "WAIT_EXPIRY_CAPITAL_CONCENTRATION")
        limit_check("Expiry risk exposure", projected_expiry_risk, max_expiry_risk, "WAIT_EXPIRY_RISK_CONCENTRATION")
        if projected_strike_count is None:
            checks.append({"check": "Same-strike concentration", "status": "INFO", "detail": "STRIKE_OR_EXPIRY_UNAVAILABLE"})
        elif max_same_strike is None:
            checks.append({"check": "Same-strike concentration", "status": "INFO", "detail": f"projected={projected_strike_count}; limit=NOT_CONFIGURED"})
        elif projected_strike_count > int(max_same_strike):
            waits.append("WAIT_SAME_STRIKE_CONCENTRATION")
            checks.append({"check": "Same-strike concentration", "status": "WAIT", "detail": f"projected={projected_strike_count}; limit={int(max_same_strike)}"})
        else:
            checks.append({"check": "Same-strike concentration", "status": "PASS", "detail": f"projected={projected_strike_count}; limit={int(max_same_strike)}"})

        base_outcome = str(row.get("portfolio_outcome") or "")
        base_reason = str(row.get("portfolio_reason") or "")
        if rejects:
            outcome = "REJECT"
            reason = ", ".join(rejects)
        elif base_outcome == "REJECT":
            outcome, reason = base_outcome, base_reason
        elif waits:
            outcome = "WAIT"
            reason = ", ".join(waits)
        else:
            outcome, reason = base_outcome, base_reason

        if outcome == "PORTFOLIO_READY_READ_ONLY":
            if key:
                proposed_ids.add(key)
            _add(side_capital, side, capital)
            _add(side_risk, side, risk)
            _add(expiry_capital, expiry, capital)
            _add(expiry_risk, expiry, risk)
            if strike_key:
                strike_counts[strike_key] = strike_counts.get(strike_key, 0) + 1

        rows.append({
            **row,
            "contract_exposure_key": key,
            "contract_identity_confidence": identity["confidence"],
            "candidate_capital_exposure": round(capital, 2) if capital is not None else None,
            "candidate_risk_exposure": round(risk, 2) if risk is not None else None,
            "projected_side_capital_exposure": round(projected_side_capital, 2) if projected_side_capital is not None else None,
            "projected_side_risk_exposure": round(projected_side_risk, 2) if projected_side_risk is not None else None,
            "projected_expiry_capital_exposure": round(projected_expiry_capital, 2) if projected_expiry_capital is not None else None,
            "projected_expiry_risk_exposure": round(projected_expiry_risk, 2) if projected_expiry_risk is not None else None,
            "projected_same_strike_positions": projected_strike_count,
            "portfolio_outcome": outcome,
            "portfolio_reason": reason,
            "checks": checks,
            "exposure_model_version": EXPOSURE_MODEL_VERSION,
            "policy_action": "OBSERVE_ONLY",
            "persisted": False,
            "reserved": False,
            "bundle_consumed": False,
            "submitted": False,
        })

    return {
        **dict(portfolio_result),
        "rows": rows,
        "outcome": (
            "PORTFOLIO_READY_READ_ONLY" if any(row.get("portfolio_outcome") == "PORTFOLIO_READY_READ_ONLY" for row in rows)
            else "REJECT" if any(row.get("portfolio_outcome") == "REJECT" for row in rows)
            else "WAIT" if rows else "NOT_ELIGIBLE"
        ),
        "ce_capital_exposure": round(side_capital.get("CE", 0.0), 2),
        "pe_capital_exposure": round(side_capital.get("PE", 0.0), 2),
        "ce_risk_exposure": round(side_risk.get("CE", 0.0), 2),
        "pe_risk_exposure": round(side_risk.get("PE", 0.0), 2),
        "expiry_capital_exposure": {key: round(value, 2) for key, value in expiry_capital.items()},
        "expiry_risk_exposure": {key: round(value, 2) for key, value in expiry_risk.items()},
        "same_strike_counts": dict(strike_counts),
        "exposure_model_version": EXPOSURE_MODEL_VERSION,
        "policy_action": "OBSERVE_ONLY",
        "persisted": False,
        "reserved": False,
        "bundle_consumed": False,
        "submitted": False,
    }
