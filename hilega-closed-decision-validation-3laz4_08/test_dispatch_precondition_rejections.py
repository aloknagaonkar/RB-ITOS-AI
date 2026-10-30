"""Additional rejection tests; synthetic preparation and temporary DBs only."""
from copy import deepcopy
from datetime import timedelta
import importlib.util
import json
from pathlib import Path

import pytest

from test_hilega_application_preparation_v1 import env, process
from test_hilega_atomic_disabled_binding_v1 import bound_env
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import read_sources

path = Path(__file__).resolve().parent / "dispatch_precondition_review.py"
spec = importlib.util.spec_from_file_location("dispatch_rejection_target", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def prepared(bound_env):
    e = bound_env
    process(e)
    source = read_sources(
        e["store"].path, e["adapter_store"].path, PIN["scope"])
    return e, source


def reject(e, source, *, pin=None, as_of=None):
    original = deepcopy(source)
    result = module.review(
        source, PIN if pin is None else pin,
        as_of=as_of or e["clock"][0].isoformat(),
    )
    assert result["reference_checks_passed"] is False, result
    assert result["reasons"], result
    for flag in (
        "entry_permission", "orders_sent", "production_execution_enabled",
        "reservation_release_permission", "production_ready",
    ):
        assert result[flag] is False
    assert source == original
    with e["adapter_store"].tx() as db:
        for table in ("attempts", "receipts"):
            assert db.execute(
                "SELECT COUNT(*) FROM " + table
            ).fetchone()[0] == 0
    return result


def test_stale_preparation_blocks(prepared):
    e, source = prepared
    reject(e, source, as_of=(
        e["clock"][0] + timedelta(seconds=61)).isoformat())


def test_future_request_blocks(prepared):
    e, source = prepared
    reject(e, source, as_of=(
        e["clock"][0] - timedelta(minutes=1)).isoformat())


def test_account_mismatch_blocks(prepared):
    e, source = prepared
    result = reject(e, source, pin=dict(PIN, scope="FIXTURE:OTHER"))
    assert result["reasons"] == ["CLOSED_PINNED_SOURCE_REQUIRED"]


def test_changed_request_fingerprint_blocks(prepared):
    e, source = prepared
    key, fingerprint, raw = source["requests"][0]
    source["requests"][0] = (key, "0" * 64, raw)
    result = reject(e, source)
    assert result["reasons"] == ["REQUEST_FINGERPRINT_MISMATCH"]


def test_changed_binding_blocks(prepared):
    e, source = prepared
    binding = next(iter(source["bindings"].values()))
    binding["plan_fingerprint"] = "0" * 64
    result = reject(e, source)
    assert result["reasons"] == ["APPLICATION_BINDING_HASH_MISMATCH"]


def test_missing_bound_request_blocks(prepared):
    e, source = prepared
    source["requests"] = []
    result = reject(e, source)
    assert result["reasons"] == ["BOUND_REQUEST_MISSING"]


def test_in_flight_request_blocks(prepared):
    e, source = prepared
    key, fingerprint, raw = source["requests"][0]
    request = json.loads(raw)
    request["state"] = "IN_FLIGHT"
    source["requests"][0] = (key, fingerprint, json.dumps(request))
    result = reject(e, source)
    assert result["reasons"] == ["UNSUBMITTED_PREPARED_REQUEST_REQUIRED"]


def test_existing_place_attempt_blocks(prepared):
    e, source = prepared
    key = source["requests"][0][0]
    attempt = dict(
        attempt_id="synthetic-existing-attempt",
        request_id=key, operation="PLACE", state="IN_FLIGHT",
    )
    source["attempts"] = [
        (attempt["attempt_id"], key, "PLACE", json.dumps(attempt))
    ]
    result = reject(e, source)
    assert result["reasons"] == [
        "EXISTING_ATTEMPT_OR_RECEIPT_REQUIRES_RECONCILIATION"]


def test_orphan_receipt_blocks(prepared):
    e, source = prepared
    source["receipts"] = {"synthetic-orphan": "{}"}
    result = reject(e, source)
    assert result["reasons"] == ["ORPHAN_ATTEMPT_OR_RECEIPT"]