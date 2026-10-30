"""Synthetic installed-Source preparation reviewed without dispatch."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from test_hilega_application_preparation_v1 import env, process
from test_hilega_atomic_disabled_binding_v1 import bound_env
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import read_sources
from market_lab.hilega_production_account_adapter_v1 import sign

path = Path.home() / "dispatch_precondition_review.py"
spec = importlib.util.spec_from_file_location("dispatch_review_test_target", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def prepared(bound_env):
    e = bound_env
    process(e)
    source = read_sources(
        e["store"].path, e["adapter_store"].path, PIN["scope"])
    return e, source


def assess(e, source):
    return module.review(source, PIN, as_of=e["clock"][0].isoformat())


def test_valid_references_never_authorize_dispatch(prepared):
    e, source = prepared
    original = deepcopy(source)
    result = assess(e, source)
    assert result["reference_checks_passed"] is True, result
    assert result["entry_permission"] is False
    assert result["production_execution_enabled"] is False
    assert result["orders_sent"] is False
    assert result["dispatch_blockers"]
    assert source == original
    with e["adapter_store"].tx() as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0


def test_reservation_signature_tampering_blocks(prepared):
    e, source = prepared
    row = next(iter(source["cash_reservations"].values()))
    row["held_cents"] += 1
    result = assess(e, source)
    assert result["reference_checks_passed"] is False
    assert result["reasons"] == ["LOCAL_CASH_RESERVATION_SIGNATURE_INVALID"]


def test_unknown_outcome_retains_hold(prepared):
    e, source = prepared
    row = next(iter(source["cash_reservations"].values()))
    row["state"] = "UNKNOWN_HOLD_RETAINED"
    row.pop("signature")
    row["signature"] = sign(row, PIN)
    result = assess(e, source)
    assert result["reasons"] == ["UNKNOWN_OUTCOME_HOLD_RETAINED"]
    assert result["reservation_release_permission"] is False


def test_pending_stop_blocks(prepared):
    e, source = prepared
    source["stop_state"] = [1, 0]
    result = assess(e, source)
    assert result["reasons"] == ["STOP_STATE_UNRESOLVED"]


def test_missing_reservation_blocks(prepared):
    e, source = prepared
    source["cash_reservations"] = {}
    result = assess(e, source)
    assert result["reasons"] == ["SINGLE_LOCAL_RESERVATION_REQUIRED"]