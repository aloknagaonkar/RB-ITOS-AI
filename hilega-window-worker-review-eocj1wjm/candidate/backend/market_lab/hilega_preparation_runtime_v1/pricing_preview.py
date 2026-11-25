"""Signed evidence plus scoped price-grid review; no execution authority."""
from copy import deepcopy

from .evidence import validate, FLAGS
from market_lab.hilega_nifty_option_price_grid_v1 import (
    inspect_quote, PricingBlocked,
)


def preview(bundle, pin, *, as_of, profile):
    # Signature, account, freshness, market, contract and cash checks run first.
    validated = validate(bundle, pin, as_of=as_of)
    plans = deepcopy(validated)

    for plan in plans:
        errors = []
        try:
            pricing = inspect_quote(
                plan["contract"], plan["quote"], profile=profile
            )
        except PricingBlocked as exc:
            errors = ["PRICE_GRID_" + str(exc)]
            pricing = {
                "status": "BLOCKED",
                "reasons": errors,
                "tick_units_verified": False,
                "executable_request_created": False,
                "entry_permission": False,
                "production_ready": False,
            }

        plan["pricing_preview"] = pricing
        plan["reasons"] = sorted(set(plan["reasons"] + errors))
        plan["evidence_checks_passed"] = (
            plan["evidence_checks_passed"] and not errors
        )
        plan["preparation_blockers"] = sorted(set(
            plan["reasons"] + [
                "TICK_UNITS_APPROVAL_PENDING",
                "EXECUTABLE_PRICE_POLICY_PENDING",
                "REAL_CASH_RESERVATION_PENDING",
            ]
        ))
        plan.update(FLAGS)
        plan.update(
            tick_units_verified=False,
            executable_request_created=False,
            production_ready=False,
        )

    return {
        **FLAGS,
        "model": "HILEGA_NON_EXECUTABLE_PRICING_PREVIEW_V1",
        "status": (
            "NOT_CLEARED" if any(p["reasons"] for p in plans)
            else "NON_EXECUTABLE_PREVIEW"
        ),
        "assessed_at": as_of,
        "plans": plans,
        "controller_checks_performed": False,
        "tick_units_verified": False,
        "executable_request_created": False,
        "production_ready": False,
    }
