"""Synthetic signed evidence; no real credentials or broker calls."""
from copy import deepcopy
import sqlite3

import pytest

from hilega_application_preparation_fixtures import (
    bundle, PIN, ts, resign, resign_cash,
)
from market_lab.hilega_preparation_runtime_v1.evidence import Blocked, FLAGS
from market_lab.hilega_preparation_runtime_v1.pricing_preview import preview
from market_lab.hilega_nifty_option_price_grid_v1 import PROFILE


def run(value, **kwargs):
    return preview(value, PIN, as_of=kwargs.get("as_of", ts(3)),
                   profile=kwargs.get("profile", PROFILE))


def test_signed_evidence_integrates_with_price_grid():
    value = bundle()
    before = deepcopy(value)
    result = run(value)
    assert value == before
    assert len(result["plans"]) == 2
    for plan in result["plans"]:
        assert plan["pricing_preview"]["normalized_tick_rupees"] == "0.05"
        assert plan["pricing_preview"]["bid_and_ask_on_grid"] is True
        assert "TICK_UNITS_APPROVAL_PENDING" in plan["preparation_blockers"]


def test_all_permissions_remain_false():
    result = run(bundle())
    for value in [result] + result["plans"]:
        for flag in FLAGS:
            assert value[flag] is False
        assert value["tick_units_verified"] is False
        assert value["executable_request_created"] is False
        assert value["production_ready"] is False


def test_bad_signature_is_rejected_before_preview():
    value = bundle()
    value["spot_initial"] += 1
    with pytest.raises(Blocked, match="SIGNATURE"):
        run(value)


def test_stale_evidence_is_not_refreshed_by_preview():
    with pytest.raises(Blocked, match="STALE"):
        run(bundle(), as_of=ts(60))


def test_zero_cash_blockers_are_preserved():
    value = bundle()
    for funds in (
        value["cash_before_market"], value["cash_after_market"],
        value["cash_capture"]["funds_before"],
        value["cash_capture"]["funds_after"],
    ):
        funds["cash_available_to_trade"] = "0"
    resign_cash(value)
    result = run(value)
    assert result["status"] == "NOT_CLEARED"
    for plan in result["plans"]:
        assert "NO_CASH_CAPACITY" in plan["reasons"]
        assert "HALF_CASH_CAP_EXCEEDED" in plan["reasons"]
        assert plan["evidence_checks_passed"] is False
        assert plan["pricing_preview"]["bid_and_ask_on_grid"] is True


def test_unsupported_profile_blocks_pricing():
    result = run(bundle(), profile="UNREVIEWED")
    assert result["status"] == "NOT_CLEARED"
    for plan in result["plans"]:
        assert "PRICE_GRID_TICK_PROFILE_UNSUPPORTED" in plan["reasons"]
        assert plan["evidence_checks_passed"] is False


def test_off_grid_ask_is_not_silently_rounded():
    value = bundle()
    for key, quote in value["quotes"].items():
        if key.startswith("NSE_FO|"):
            quote["depth"]["sell"][0]["price"] = 100.01
    resign(value)
    result = run(value)
    assert result["status"] == "NOT_CLEARED"
    for plan in result["plans"]:
        assert "PRICE_GRID_PRICE_OFF_TICK_GRID" in plan["reasons"]


def test_preview_does_not_access_databases(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Preview attempted database access")
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    assert run(bundle())["production_ready"] is False
