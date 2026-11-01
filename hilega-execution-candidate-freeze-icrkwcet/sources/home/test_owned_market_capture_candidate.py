from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest

import owned_market_capture_candidate as capture
from priced_exit_transaction_candidate import submit_priced_exit_candidate
from test_owned_exit_pricing_candidate import (
    synthetic_scope, env, bound_env, live_case, candidate, priced,
)
from hilega_application_preparation_fixtures import PIN


@pytest.fixture
def collector(priced, monkeypatch):
    rules, market, cash, analysis = capture.collectors()
    monkeypatch.setattr(
        capture, "collectors", lambda: (rules, market, cash, analysis))
    original = priced[4]
    state = dict(
        contracts=deepcopy(original["contracts"]),
        quotes=deepcopy(original["quotes"]),
        bad_second_profile=False,
    )
    account_calls, market_calls = [], []

    def account_get(self, name):
        account_calls.append(name)
        assert name == "profile", "Owned quote capture must not read funds"
        uid = "SYNTHETIC_PROVIDER_TEST"
        if state["bad_second_profile"] and len(account_calls) == 2:
            uid = "OTHER_SYNTHETIC_ACCOUNT"
        return dict(status="success", data=dict(
            broker="UPSTOX", is_active=True, user_id=uid))

    def market_get(self, name, keys=None):
        market_calls.append((name, keys))
        if name == "market":
            return deepcopy(original["market_before"])
        if name == "contracts":
            return deepcopy(state["contracts"])
        if name == "quotes":
            assert keys == [priced[5]["instrument_key"]]
            return deepcopy(state["quotes"])
        raise AssertionError("Unexpected market endpoint")

    monkeypatch.setattr(capture.Client, "get", account_get)
    monkeypatch.setattr(market.MarketClient, "get", market_get)
    return state, account_calls, market_calls


def run(priced, clock=None):
    return capture.capture_owned_market(
        "SYNTHETIC-NOT-A-REAL-TOKEN", PIN, priced[5],
        quantity=priced[8]["draft"]["body"]["quantity"],
        clock=clock or (lambda: priced[3]),
    )


def test_exact_owned_quote_without_funds_or_atm(priced, collector):
    state, account_calls, market_calls = collector
    result = run(priced)
    assert account_calls == ["profile", "profile"]
    assert [name for name, keys in market_calls] == [
        "market", "contracts", "quotes", "market"]
    assert list(result["quotes"]) == [priced[5]["instrument_key"]]
    assert result["cash_capture"] is None
    assert result["spot_initial"] is None
    assert result["production_execution_enabled"] is False


def test_missing_owned_contract_blocks(priced, collector):
    collector[0]["contracts"] = []
    with pytest.raises(ValueError, match="OWNED_CONTRACT_NOT_UNIQUE"):
        run(priced)
    assert not any(name == "quotes" for name, keys in collector[2])


def test_missing_owned_quote_blocks(priced, collector):
    collector[0]["quotes"] = {}
    with pytest.raises(ValueError, match="QUOTE_IDENTITY_MISSING"):
        run(priced)


def test_profile_change_after_market_sweep_blocks(priced, collector):
    collector[0]["bad_second_profile"] = True
    with pytest.raises(ValueError, match="BROKER_ACCOUNT_MISMATCH"):
        run(priced)


def test_slow_capture_blocks(priced, collector):
    at = priced[3]
    times = iter([at, at+timedelta(seconds=31)])
    with pytest.raises(ValueError):
        run(priced, clock=lambda: next(times))


def test_provider_defers_token_access(priced, collector):
    token = Mock(return_value="SYNTHETIC-NOT-A-REAL-TOKEN")
    provider = capture.make_owned_market_provider(
        token, PIN, priced[5],
        quantity=priced[8]["draft"]["body"]["quantity"],
        clock=lambda: priced[3],
    )
    token.assert_not_called()
    provider()
    token.assert_called_once()


def test_collector_connects_to_priced_sell_transaction(priced, collector):
    e, key, snapshot, at, old, contract, adapter, mod, saved, authority, seq = priced
    provider = capture.make_owned_market_provider(
        lambda: "SYNTHETIC-NOT-A-REAL-TOKEN", PIN, contract,
        quantity=saved["draft"]["body"]["quantity"], clock=lambda: at)

    def receipt(aid, wire):
        return dict(
            attempt_id=aid, wire_fingerprint=mod.sha(wire),
            origin="LOCAL_HTTP_TRANSPORT", http_status=200,
            body=dict(status="success", data=dict(
                order_ids=["SYNTHETIC-OWNED-CAPTURE-SELL"])))

    with patch.object(adapter.transport, "check", return_value=None), patch.object(
        adapter.transport, "send", side_effect=receipt,
    ) as send:
        result = submit_priced_exit_candidate(
            e["store"], adapter, PIN, authority,
            adapter_module=mod, entry_id=key,
            request_id=saved["request_id"], journal=e["path"],
            exit_sequence=seq, capture_provider=lambda: deepcopy(snapshot),
            market_capture_provider=provider, clock=lambda: at,
        )
    assert result["status"] == "CANDIDATE_EXIT_ATTEMPT_RECORDED"
    send.assert_called_once()
