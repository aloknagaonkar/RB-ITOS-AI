"""Rehashed mutations of synthetic review inputs; no production writes."""
from copy import deepcopy
import json

import pytest

from test_dispatch_precondition_review import module, prepared, env, bound_env
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_preparation_runtime_v1.evidence import digest
from market_lab.hilega_production_account_adapter_v1 import sign
from market_lab.hilega_preparation_runtime_v1.ownership_checks import (
    risk_evidence_audit as audit,
)


def rebind(source):
    key, _, raw = source["requests"][0]
    request = json.loads(raw)
    candidate = source["outbox"][key]["disabled_request_candidate"]
    request["draft"] = deepcopy(candidate["draft"])
    request["draft"]["fingerprint"] = digest(request["draft"]["body"])
    candidate["draft"] = deepcopy(request["draft"])

    stable = {
        k: request[k] for k in (
            "request_id", "draft", "signal_id", "signal_at",
            "direction", "reservation_reference",
        )
    }
    fingerprint = digest(stable)
    source["requests"][0] = (key, fingerprint, json.dumps(request))

    binding = source["bindings"][key]
    binding.update(
        request_fingerprint=fingerprint,
        plan_fingerprint=digest(source["plans"][key]),
        hold_fingerprint=digest(source["holds"][key]),
        outbox_fingerprint=digest(source["outbox"][key]),
    )
    reservation = source["cash_reservations"][key]
    reservation.update(
        request_fingerprint=fingerprint,
        plan_fingerprint=binding["plan_fingerprint"],
        shadow_hold_fingerprint=binding["hold_fingerprint"],
        outbox_fingerprint=binding["outbox_fingerprint"],
    )
    reservation.pop("signature", None)
    reservation["signature"] = sign(reservation, PIN)
    # Prove ordinary local hash/reference checks accept the modified inputs.
    audit.assess(source)
    return key


@pytest.mark.parametrize("case,expected", [
    ("price", "LIMIT_PRICE_DIFFERS_FROM_OBSERVED_ASK"),
    ("premium", "CANDIDATE_PREMIUM_MISMATCH"),
    ("buffer", "RESERVATION_COST_COMPONENT_MISMATCH"),
    ("budget", "CANDIDATE_BUDGET_ARITHMETIC_MISMATCH"),
    ("quantity", "CURRENT_PREVIEW_CONTRACT_MISMATCH"),
])
def test_rehashed_mutation_still_blocked(prepared, case, expected):
    e, source = prepared
    key = source["requests"][0][0]
    candidate = source["outbox"][key]["disabled_request_candidate"]
    body = candidate["draft"]["body"]

    if case == "price":
        body["price"] = 101
    elif case == "premium":
        candidate["premium_cents"] += 1
    elif case == "buffer":
        candidate["fee_buffer_cents"] += 1
        candidate["budget_cents"] += 1
    elif case == "budget":
        candidate["budget_cents"] -= 1
    else:
        body["quantity"] = 130
        source["plans"][key]["quantity"] = 130
        source["outbox"][key]["quantity"] = 130

    rebind(source)
    before = deepcopy(source)
    result = module.review(
        source, PIN, as_of=e["clock"][0].isoformat())
    assert result["reference_checks_passed"] is False, result
    assert result["reasons"] == [expected], result
    assert result["entry_permission"] is False
    assert result["production_execution_enabled"] is False
    assert result["reservation_release_permission"] is False
    assert source == before

    with e["adapter_store"].tx() as db:
        for table in ("attempts", "receipts"):
            assert db.execute(
                "SELECT COUNT(*) FROM " + table
            ).fetchone()[0] == 0