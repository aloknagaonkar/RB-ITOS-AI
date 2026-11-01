from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import Mock, patch

import pytest

from owned_exit_pricing_candidate import review_owned_quote, prepare_exit_at_bid
from priced_exit_transaction_candidate import submit_priced_exit_candidate
from test_live_closed_lifecycle_candidate import (
    synthetic_scope, env, bound_env, live_case,
)
from test_production_authorizer_hook import candidate
from test_hilega_application_preparation_v1 import append
from hilega_application_preparation_fixtures import PIN
from market_lab.hilega_production_simulator_bridge_v1 import verified_records, accepted
from market_lab.hilega_preparation_runtime_v1.ownership_checks.risk_evidence_audit import read_sources
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign

EXIT = "STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21"


@pytest.fixture
def priced(live_case, candidate):
    e, entry_id, snapshot, at = live_case
    source = read_sources(e["store"].path, e["adapter_store"].path, PIN["scope"])
    bundle = json.loads(source["evidence"][
        source["bindings"][entry_id]["bundle_fingerprint"]])
    contract = source["plans"][entry_id]["evidence"]["contract"]
    store = candidate.Store(e["adapter_store"].path, PIN["scope"], "LIVE_CLOSED")
    token = Mock(side_effect=AssertionError("No credentials permitted"))
    adapter = candidate.Adapter(store, candidate.HttpTransport(token))
    append(e["path"], [EXIT])
    record = verified_records(e["path"])[-1]
    event = accepted(record)[0]
    saved = prepare_exit_at_bid(
        adapter, source, event, bundle, PIN,
        entry_id=entry_id, clock=lambda: at)
    authority = dict(
        authority_id="SYNTHETIC-PRICED-EXIT-AUTHORITY",
        account_scope=PIN["scope"], key="77"*32)
    return e, entry_id, snapshot, at, bundle, contract, adapter, candidate, saved, authority, record["sequence"]


def resign(bundle):
    bundle.pop("signature", None)
    bundle["signature"] = sign(bundle, PIN)


def quote_row(case, bundle):
    return next(q for q in bundle["quotes"].values()
                if q["instrument_token"] == case[5]["instrument_key"])


def assess(case, bundle=None, at=None):
    return review_owned_quote(
        bundle or case[4], PIN, case[5],
        quantity=case[8]["draft"]["body"]["quantity"],
        as_of=(at or case[3]).isoformat())


def test_owned_quote_sets_bid_without_production_approval(priced):
    result = assess(priced)
    assert float(result["limit_price"]) == priced[8]["draft"]["body"]["price"]
    assert result["pricing_policy_approved"] is False


def test_exit_quote_does_not_require_cash_or_current_atm(priced):
    bundle = deepcopy(priced[4])
    bundle["cash_capture"] = None
    bundle["cash_before_market"] = None
    bundle["cash_after_market"] = None
    bundle["spot_initial"] = 1
    resign(bundle)
    assert assess(priced, bundle)["instrument"] == priced[5]["instrument_key"]


def test_stale_quote_blocks(priced):
    with pytest.raises(ValueError):
        assess(priced, at=priced[3]+timedelta(seconds=31))


def test_crossed_quote_blocks(priced):
    bundle = deepcopy(priced[4])
    row = quote_row(priced, bundle)
    ask = min(float(x["price"]) for x in row["depth"]["sell"]
              if float(x["quantity"]) > 0)
    row["depth"]["buy"][0]["price"] = ask + 1
    resign(bundle)
    with pytest.raises(ValueError):
        assess(priced, bundle)


def test_off_grid_quote_blocks(priced):
    bundle = deepcopy(priced[4])
    row = quote_row(priced, bundle)
    bid = max(float(x["price"]) for x in row["depth"]["buy"]
              if float(x["quantity"]) > 0)
    row["depth"]["buy"][0]["price"] = str(round(bid + 0.01, 2))
    resign(bundle)
    with pytest.raises(ValueError):
        assess(priced, bundle)


def test_tampered_quote_blocks(priced):
    bundle = deepcopy(priced[4])
    bundle["spot_initial"] = 2
    with pytest.raises(ValueError, match="EXIT_MARKET_SIGNATURE_INVALID"):
        assess(priced, bundle)


def test_priced_sell_revalidates_inside_attempt_transaction(priced):
    e, key, snapshot, at, bundle, contract, adapter, mod, saved, authority, seq = priced

    def receipt(aid, wire):
        return dict(
            attempt_id=aid, wire_fingerprint=mod.sha(wire),
            origin="LOCAL_HTTP_TRANSPORT", http_status=200,
            body=dict(status="success", data=dict(
                order_ids=["SYNTHETIC-PRICED-SELL"])))

    with patch.object(adapter.transport, "check", return_value=None), patch.object(
        adapter.transport, "send", side_effect=receipt,
    ) as send:
        result = submit_priced_exit_candidate(
            e["store"], adapter, PIN, authority,
            adapter_module=mod, entry_id=key,
            request_id=saved["request_id"], journal=e["path"],
            exit_sequence=seq,
            capture_provider=lambda: deepcopy(snapshot),
            market_capture_provider=lambda: deepcopy(bundle),
            clock=lambda: at,
        )
    assert result["status"] == "CANDIDATE_EXIT_ATTEMPT_RECORDED"
    send.assert_called_once()
