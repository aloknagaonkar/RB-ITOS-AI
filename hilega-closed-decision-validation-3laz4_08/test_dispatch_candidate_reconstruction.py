"""Candidate reconstruction tests using synthetic preparation inputs."""
from copy import deepcopy
from datetime import timedelta
import json

import pytest

from test_dispatch_precondition_review import module, prepared, env, bound_env
from test_dispatch_rehashed_cost import rebind
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1.evidence import digest
from market_lab.hilega_production_account_adapter_v1 import sign


def assess(e, source, *, at=None):
    return module.review(
        source, PIN, as_of=(at or e["clock"][0]).isoformat())


def assert_closed(result):
    for key in (
        "entry_permission", "orders_sent", "production_execution_enabled",
        "reservation_release_permission", "production_ready",
    ):
        assert result[key] is False


def test_candidate_input_fingerprint_rebuilt(prepared):
    e, source = prepared
    key = source["requests"][0][0]
    candidate = source["outbox"][key]["disabled_request_candidate"]
    candidate["input_fingerprint"] = "0" * 64
    rebind(source)
    result = assess(e, source)
    assert result["reasons"] == ["CANDIDATE_RECONSTRUCTION_MISMATCH"], result
    assert_closed(result)


def test_candidate_age_over_ten_seconds_blocks(prepared):
    e, source = prepared
    request = json.loads(source["requests"][0][2])
    from datetime import datetime
    created = request["draft"]["created_at"]
    at = datetime.fromisoformat(created) + timedelta(seconds=11)
    with pytest.raises(ValueError, match="^CANDIDATE_STALE_OR_FUTURE$"):
        module.verify_candidate_age(created, at.isoformat())

    # The complete review also blocks: fixture quotes have expired first.
    result = assess(e, source, at=at)
    assert result["reference_checks_passed"] is False
    assert result["reasons"] == ["PREPARATION_EVIDENCE_NOT_CLEARED"], result
    assert_closed(result)


def test_candidate_age_exactly_ten_seconds(prepared):
    e, source = prepared
    request = json.loads(source["requests"][0][2])
    from datetime import datetime
    created = request["draft"]["created_at"]
    at = datetime.fromisoformat(created) + timedelta(seconds=10)
    assert module.verify_candidate_age(created, at.isoformat()) == 10

    # Candidate age alone cannot override expired quote evidence.
    result = assess(e, source, at=at)
    assert result["reference_checks_passed"] is False
    assert result["reasons"] == ["PREPARATION_EVIDENCE_NOT_CLEARED"], result
    assert_closed(result)


def test_control_session_mismatch_blocks(prepared):
    e, source = prepared
    source["control"]["session_date"] = "2026-10-25"
    result = assess(e, source)
    assert result["reasons"] == ["CONTROL_SESSION_MISMATCH"], result
    assert_closed(result)


def test_rehashed_candidate_policy_change_blocks(prepared):
    e, source = prepared
    key = source["requests"][0][0]
    source["outbox"][key]["disabled_request_candidate"]["policy_id"] = (
        "SYNTHETIC_OTHER_POLICY")
    rebind(source)
    result = assess(e, source)
    assert result["reasons"] == ["CANDIDATE_RECONSTRUCTION_MISMATCH"], result
    assert_closed(result)


def test_rehashed_unexpected_candidate_field_blocks(prepared):
    e, source = prepared
    key = source["requests"][0][0]
    source["outbox"][key]["disabled_request_candidate"]["unexpected"] = True
    rebind(source)
    before = deepcopy(source)
    result = assess(e, source)
    assert result["reasons"] == ["CANDIDATE_RECONSTRUCTION_MISMATCH"], result
    assert source == before
    assert_closed(result)