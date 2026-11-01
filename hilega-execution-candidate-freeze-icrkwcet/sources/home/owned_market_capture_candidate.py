"""Fixed GET-only owned-option capture. No ATM selection, funds or orders."""
from copy import deepcopy
from datetime import datetime, timezone
import uuid

from market_lab.hilega_preparation_runtime_v1.collect import collectors
from market_lab.hilega_preparation_runtime_v1.evidence import (
    MODEL, MODE, FLAGS, fresh_window,
)
from market_lab.hilega_production_account_adapter_v1 import (
    Client, matches, sign, day,
)
from market_lab.hilega_nifty_option_price_grid_v1 import PROFILE, normalized_tick
from owned_exit_pricing_candidate import review_owned_quote


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def capture_owned_market(
    token, pin, contract, *, quantity,
    clock=lambda: datetime.now(timezone.utc),
):
    rules, market_module, _, _ = collectors()
    normalized_tick(contract, profile=PROFILE)
    account = Client(token)
    market = market_module.MarketClient(token)
    start = clock()
    matches(account.get("profile"), pin)
    opening = market.get("market")

    contracts = market.get("contracts")
    need(isinstance(contracts, list), "CONTRACT_LIST_REQUIRED")
    matching = [
        row for row in contracts if isinstance(row, dict)
        and row.get("instrument_key") == contract["instrument_key"]
    ]
    need(len(matching) == 1, "OWNED_CONTRACT_NOT_UNIQUE_IN_FRESH_LIST")
    need(all(key in matching[0] and matching[0][key] == value
             for key, value in contract.items()),
         "OWNED_CONTRACT_CHANGED")
    instrument = contract["instrument_key"]
    quote = rules.quote_map(
        market.get("quotes", [instrument]), [instrument],
    )[instrument]
    safe_quote = {
        key: quote[key] for key in (
            "instrument_token", "last_price", "timestamp",
            "last_trade_time", "volume",
        )
    }
    safe_quote["depth"] = {
        side: [
            {key: row[key] for key in ("price", "quantity")}
            for row in quote["depth"][side]
        ] for side in ("buy", "sell")
    }
    closing = market.get("market")
    matches(account.get("profile"), pin)
    end = clock()
    fresh_window(start.isoformat(), end.isoformat(), end.isoformat())
    bundle = dict(
        FLAGS,
        model=MODEL, evidence_mode=MODE, snapshot_id=uuid.uuid4().hex,
        account_scope=pin["scope"],
        started_at=start.isoformat(), completed_at=end.isoformat(),
        session_date=day(end), profile_verified_before_and_after=True,
        capture_scope="OWNED_EXIT_QUOTE_ONLY",
        market_before={key: opening[key] for key in ("exchange", "status")},
        market_after={key: closing[key] for key in ("exchange", "status")},
        contracts=[deepcopy(contract)], quotes={instrument: safe_quote},
        # Deliberately not an entry cash/preparation bundle.
        cash_capture=None, cash_before_market=None, cash_after_market=None,
        spot_initial=None,
    )
    bundle["signature"] = sign(bundle, pin)
    review_owned_quote(
        bundle, pin, contract, quantity=quantity, as_of=end.isoformat())
    return bundle


def make_owned_market_provider(token_provider, pin, contract, *, quantity, clock):
    need(callable(token_provider), "TOKEN_PROVIDER_REQUIRED")
    pinned, selected = deepcopy(pin), deepcopy(contract)

    def provide():
        token = token_provider()
        try:
            return capture_owned_market(
                token, pinned, selected, quantity=quantity, clock=clock)
        finally:
            del token

    return provide
