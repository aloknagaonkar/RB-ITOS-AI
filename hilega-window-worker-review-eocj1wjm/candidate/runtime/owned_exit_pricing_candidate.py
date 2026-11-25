"""Owned-contract SELL-at-bid candidate. No production pricing approval."""
import hmac
from decimal import Decimal

from market_lab.hilega_preparation_runtime_v1.evidence import (
    MODEL, MODE, FLAGS, dependencies, fresh_window,
)
from market_lab.hilega_preparation_runtime_v1.ownership_checks.signature_checks import sign, aware
from market_lab.hilega_preparation_runtime_v1.ownership_checks.historical_receipt_checks import sha
from market_lab.hilega_nifty_option_price_grid_v1 import PROFILE, inspect_quote, normalized_tick
from market_lab.hilega_execution_port_v1.mapping import draft

POLICY = "CANDIDATE_OWNED_ONE_LOT_SELL_LIMIT_AT_BID_V1"


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def review_owned_quote(bundle, pin, contract, *, quantity, as_of):
    rules, _ = dependencies()
    value = dict(bundle)
    signed = value.pop("signature", None)
    need(isinstance(signed, str)
         and hmac.compare_digest(sign(value, pin), signed),
         "EXIT_MARKET_SIGNATURE_INVALID")
    need(value.get("model") == MODEL and value.get("evidence_mode") == MODE
         and value.get("account_scope") == pin["scope"]
         and value.get("profile_verified_before_and_after") is True
         and all(value.get(flag) is False for flag in FLAGS),
         "EXIT_MARKET_ACCOUNT_OR_FLAGS_INVALID")
    now = fresh_window(value["started_at"], value["completed_at"], as_of)
    need(value["session_date"] == rules.day(now)
         if hasattr(rules, "day") else
         value["session_date"] == now.astimezone(rules.IST).date().isoformat(),
         "EXIT_MARKET_SESSION_INVALID")
    need(value.get("market_before", {}).get("exchange") == "NSE"
         and value.get("market_after", {}).get("exchange") == "NSE"
         and value["market_before"].get("status")
             == value["market_after"].get("status") == "NORMAL_OPEN",
         "EXIT_MARKET_NOT_NORMAL_OPEN")
    instrument = contract["instrument_key"]
    matching = [c for c in value["contracts"]
                if c["instrument_key"] == instrument]
    need(len(matching) == 1 and matching[0] == contract,
         "OWNED_EXIT_CONTRACT_CHANGED")
    need(type(quantity) is int and quantity > 0,
         "POSITIVE_EXIT_QUANTITY_REQUIRED")
    quote = rules.quote_map(value["quotes"], [instrument])[instrument]
    quality = rules.quality(quote, quantity, now, 10, Decimal("2"))
    need(not quality["reasons"],
         "EXIT_QUOTE_QUALITY_" + "_".join(quality["reasons"]))
    grid = inspect_quote(contract, quality, profile=PROFILE)
    return dict(
        policy_id=POLICY, instrument=instrument, quantity=quantity,
        limit_price=grid["bid"], observed_ask=grid["ask"],
        market_bundle_fingerprint=sha(bundle),
        quote_fingerprint=sha(quote),
        pricing_policy_approved=False, tick_profile_approved=False,
        production_execution_enabled=False,
    )


def check_wire_price(source, bundle, pin, *, entry_id, wire, as_of):
    contract = source["plans"][entry_id]["evidence"]["contract"]
    pricing = review_owned_quote(
        bundle, pin, contract,
        quantity=wire["body"]["quantity"], as_of=as_of)
    need(Decimal(str(wire["body"]["price"])) == Decimal(pricing["limit_price"]),
         "SELL_LIMIT_DIFFERS_FROM_OBSERVED_BID")
    return pricing


def prepare_exit_at_bid(adapter, source, event, bundle, pin, *, entry_id, clock):
    import json
    parent = next(json.loads(raw) for key, fp, raw in source["requests"]
                  if key == entry_id)
    need(event["role"] == "EXIT"
         and event["direction"] == parent["direction"]
         and event.get("entry_reference_at") is not None
         and aware(event["entry_reference_at"]) == aware(parent["signal_at"]),
         "EXIT_SIGNAL_PARENT_MISMATCH")
    contract = source["plans"][entry_id]["evidence"]["contract"]
    quantity = parent["draft"]["body"]["quantity"]
    now = clock()
    pricing = review_owned_quote(
        bundle, pin, contract, quantity=quantity, as_of=now.isoformat())
    selected = dict(contract)
    for name in ("lot_size", "minimum_lot", "freeze_quantity"):
        value = selected[name]
        need(not isinstance(value, bool) and int(value) == value,
             "INTEGRAL_CONTRACT_QUANTITY_REQUIRED")
        selected[name] = int(value)
    need(quantity == selected["lot_size"], "FULL_LOT_EXIT_ONLY")
    key = sha(["PRICED_EXIT_CANDIDATE", entry_id, event["id"]])
    request = draft(
        selected, request_id=key, side="SELL", lots=1,
        as_of=now.isoformat(), order_type="LIMIT",
        limit_price=pricing["limit_price"],
        normalized_tick_rupees=normalized_tick(selected, profile=PROFILE),
    )
    return adapter.prepare(
        request, signal_id=event["id"], signal_at=event["event_at"],
        direction=event["direction"],
        reservation_reference=parent["reservation_reference"],
        as_of=now.isoformat(),
    )
