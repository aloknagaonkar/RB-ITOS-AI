from copy import deepcopy
from decimal import Decimal

import pytest

from market_lab.hilega_nifty_option_price_grid_v1 import (
    PROFILE, PricingBlocked, normalized_tick, on_grid,
    validate_price, align_price, inspect_quote,
)


def contract():
    return dict(
        instrument_key="NSE_FO|53720",
        underlying_key="NSE_INDEX|Nifty 50",
        segment="NSE_FO", exchange="NSE", instrument_type="CE",
        tick_size=5.0,
    )


@pytest.mark.parametrize("kind", ["CE", "PE"])
def test_reviewed_scope_normalizes(kind):
    c = contract()
    c["instrument_type"] = kind
    assert normalized_tick(c, profile=PROFILE) == Decimal("0.05")


@pytest.mark.parametrize("raw", [0.05, 1, 10, 0, -5, True, None, "NaN", "Infinity"])
def test_unexpected_raw_tick_is_rejected(raw):
    c = contract()
    c["tick_size"] = raw
    with pytest.raises(PricingBlocked):
        normalized_tick(c, profile=PROFILE)


@pytest.mark.parametrize("field,value", [
    ("underlying_key", "NSE_INDEX|Nifty Bank"),
    ("segment", "NSE_EQ"),
    ("exchange", "BSE"),
    ("instrument_type", "FUT"),
    ("instrument_key", "NSE_EQ|53720"),
])
def test_other_scopes_are_rejected(field, value):
    c = contract()
    c[field] = value
    with pytest.raises(PricingBlocked, match="SCOPE"):
        normalized_tick(c, profile=PROFILE)


def test_profile_must_be_explicit_and_supported():
    with pytest.raises(PricingBlocked, match="PROFILE"):
        normalized_tick(contract(), profile="UNREVIEWED")


@pytest.mark.parametrize("price", ["196.95", "182.45", "0.05", "100", Decimal("196.50")])
def test_exact_grid_prices(price):
    assert on_grid(contract(), price, profile=PROFILE)
    assert validate_price(contract(), price, profile=PROFILE) == Decimal(str(price))


def test_off_grid_is_rejected_without_silent_rounding():
    assert not on_grid(contract(), "196.951", profile=PROFILE)
    with pytest.raises(PricingBlocked, match="OFF_TICK_GRID"):
        validate_price(contract(), "196.951", profile=PROFILE)


@pytest.mark.parametrize("price", ["0", "-1", "NaN", "Infinity", True, None])
def test_invalid_prices_are_rejected(price):
    with pytest.raises(PricingBlocked):
        validate_price(contract(), price, profile=PROFILE)


def test_rounding_is_explicit_and_exact():
    c = contract()
    assert align_price(c, "196.951", profile=PROFILE, rounding="UP") == Decimal("197.00")
    assert align_price(c, "196.951", profile=PROFILE, rounding="DOWN") == Decimal("196.95")
    assert align_price(c, "196.95", profile=PROFILE, rounding="UP") == Decimal("196.95")
    with pytest.raises(PricingBlocked, match="EXPLICIT"):
        align_price(c, "196.951", profile=PROFILE, rounding="NEAREST")


def test_rounding_cannot_return_zero():
    with pytest.raises(PricingBlocked, match="NONPOSITIVE"):
        align_price(contract(), "0.01", profile=PROFILE, rounding="DOWN")


def test_float_artifact_is_not_silently_accepted():
    assert not on_grid(contract(), 0.1 + 0.2, profile=PROFILE)


def test_crossed_quote_is_rejected():
    with pytest.raises(PricingBlocked, match="CROSSED"):
        inspect_quote(contract(), {"bid": "197.00", "ask": "196.95"}, profile=PROFILE)


def test_quote_review_preserves_inputs_and_permissions():
    c = contract()
    quote = {"bid": "196.50", "ask": "196.95"}
    before = deepcopy((c, quote))
    result = inspect_quote(c, quote, profile=PROFILE)
    assert (c, quote) == before
    assert result["normalized_tick_rupees"] == "0.05"
    assert result["bid_and_ask_on_grid"] is True
    for key in (
        "tick_units_verified", "executable_request_created",
        "entry_permission", "production_ready",
    ):
        assert result[key] is False
