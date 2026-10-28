"""Scoped NIFTY option price-grid helper; no execution or broker calls.

Reference:
https://www.nseindia.com/static/products-services/equity-derivatives-nifty50
https://upstox.com/developer/api-documentation/get-option-contracts/

This explicit profile encodes the reviewed raw-5/reference-0.05 mapping.
It is not a universal Upstox unit conversion or production approval.
"""
from decimal import Decimal, InvalidOperation
import re

PROFILE = "NSE_NIFTY50_OPTIONS_RAW5_REFERENCE_005_V1"


class PricingBlocked(ValueError):
    pass


def number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise PricingBlocked("PRICE_NUMBER_REQUIRED")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise PricingBlocked("PRICE_NUMBER_INVALID") from None
    if not result.is_finite() or result <= 0:
        raise PricingBlocked("PRICE_MUST_BE_FINITE_AND_POSITIVE")
    return result


def normalized_tick(contract, *, profile):
    if profile != PROFILE:
        raise PricingBlocked("TICK_PROFILE_UNSUPPORTED")
    if not isinstance(contract, dict):
        raise PricingBlocked("CONTRACT_REQUIRED")
    if (
        contract.get("underlying_key") != "NSE_INDEX|Nifty 50"
        or contract.get("segment") != "NSE_FO"
        or contract.get("exchange") != "NSE"
        or contract.get("instrument_type") not in {"CE", "PE"}
        or not re.fullmatch(
            r"NSE_FO\|[0-9]+", str(contract.get("instrument_key", ""))
        )
    ):
        raise PricingBlocked("CONTRACT_SCOPE_UNSUPPORTED")
    if number(contract.get("tick_size")) != Decimal("5"):
        raise PricingBlocked("RAW_TICK_UNEXPECTED_FOR_PROFILE")
    return Decimal("0.05")


def _units(value):
    # Exact rational conversion: one reviewed tick is 1/20 rupee.
    numerator, denominator = number(value).as_integer_ratio()
    return numerator * 20, denominator


def on_grid(contract, price, *, profile):
    normalized_tick(contract, profile=profile)
    numerator, denominator = _units(price)
    return numerator % denominator == 0


def validate_price(contract, price, *, profile):
    value = number(price)
    if not on_grid(contract, value, profile=profile):
        raise PricingBlocked("PRICE_OFF_TICK_GRID")
    return value


def align_price(contract, price, *, profile, rounding):
    normalized_tick(contract, profile=profile)
    if rounding not in {"UP", "DOWN"}:
        raise PricingBlocked("EXPLICIT_UP_OR_DOWN_REQUIRED")
    numerator, denominator = _units(price)
    units = (
        (numerator + denominator - 1) // denominator
        if rounding == "UP" else numerator // denominator
    )
    if units <= 0:
        raise PricingBlocked("ROUNDED_PRICE_NONPOSITIVE")
    # Construct currency exactly, without Decimal-context rounding.
    paise = units * 5
    return Decimal(f"{paise // 100}.{paise % 100:02d}")


def inspect_quote(contract, quote, *, profile):
    tick = normalized_tick(contract, profile=profile)
    bid = validate_price(contract, quote["bid"], profile=profile)
    ask = validate_price(contract, quote["ask"], profile=profile)
    if bid > ask:
        raise PricingBlocked("CROSSED_QUOTE")
    return {
        "instrument": contract["instrument_key"],
        "profile": profile,
        "raw_tick_size": str(contract["tick_size"]),
        "normalized_tick_rupees": str(tick),
        "bid": str(bid),
        "ask": str(ask),
        "bid_and_ask_on_grid": True,
        "tick_units_verified": False,
        "executable_request_created": False,
        "entry_permission": False,
        "production_ready": False,
    }
