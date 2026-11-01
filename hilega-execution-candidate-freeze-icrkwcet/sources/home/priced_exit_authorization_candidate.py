"""Fresh signed quote binding around the ownership-bound SELL contract."""
from fixture_execution_authorization import signature
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import sha
from owned_exit_pricing_candidate import check_wire_price, POLICY
from production_exit_authorization_candidate import (
    issue_exit_candidate as base_issue,
    claim_exit_candidate as base_claim,
)


def issue_exit_candidate(
    authority, pin, source, snapshot, *, market_bundle, entry_id,
    request_id, wire, journal, exit_sequence, at,
):
    check_wire_price(
        source, market_bundle, pin, entry_id=entry_id, wire=wire, as_of=at)
    grant = base_issue(
        authority, pin, source, snapshot, entry_id=entry_id,
        request_id=request_id, wire=wire, journal=journal,
        exit_sequence=exit_sequence, at=at)
    grant.pop("signature")
    grant.update(
        market_bundle_fingerprint=sha(market_bundle),
        pricing_policy_id=POLICY,
        pricing_policy_approved=False,
    )
    grant["signature"] = signature(grant, authority)
    return grant


def claim_exit_candidate(
    db, grant, authority, pin, source, snapshot, *,
    market_bundle, entry_id, request_id, wire,
    journal, exit_sequence, attempt_id, at,
):
    if (grant.get("market_bundle_fingerprint") != sha(market_bundle)
            or grant.get("pricing_policy_id") != POLICY
            or grant.get("pricing_policy_approved") is not False):
        raise ValueError("EXIT_MARKET_GRANT_BINDING_MISMATCH")
    check_wire_price(
        source, market_bundle, pin, entry_id=entry_id, wire=wire, as_of=at)
    return base_claim(
        db, grant, authority, pin, source, snapshot,
        entry_id=entry_id, request_id=request_id, wire=wire,
        journal=journal, exit_sequence=exit_sequence,
        attempt_id=attempt_id, at=at,
    )
