from decimal import Decimal

import httpx
import pytest

from market_lab.hilega_upstox_broker_preflight_v1 import (
    BrokerPreflightError,
    SandboxOrderIntent,
    UpstoxLiveReadinessClient,
    UpstoxSandboxOrderClient,
    capability_manifest,
    main,
)


def test_bullish_and_bearish_option_mapping_is_enforced():
    valid = SandboxOrderIntent("t1", "v", "2026-10-04", "BULLISH", "CE", "NSE_FO|1", 75, "I", Decimal("10.5"))
    valid.validate()
    invalid = SandboxOrderIntent("t2", "v", "2026-10-04", "BULLISH", "PE", "NSE_FO|2", 75, "I", Decimal("10.5"))
    with pytest.raises(BrokerPreflightError, match="requires CE"):
        invalid.validate()


def test_place_payload_is_limit_buy_and_correlated():
    intent = SandboxOrderIntent("trade-123", "v2", "2026-10-04", "BEARISH", "PE", "NSE_FO|2", 75, "I", Decimal("12.25"))
    payload = intent.place_payload()
    assert payload["transaction_type"] == "BUY"
    assert payload["order_type"] == "LIMIT"
    assert payload["instrument_token"] == "NSE_FO|2"
    assert payload["tag"] == "HIL-trade-123"


def test_live_client_is_read_only_and_validates_profile():
    def handler(request):
        assert request.url.host == "live.test"
        assert request.url.path == "/v2/user/profile"
        return httpx.Response(200, json={"status": "success", "data": {
            "is_active": True, "exchanges": ["NSE", "NFO"],
            "products": ["I"], "order_types": ["LIMIT"],
        }})
    client = httpx.Client(base_url="https://live.test", transport=httpx.MockTransport(handler))
    adapter = UpstoxLiveReadinessClient("secret", client=client)
    assert adapter.validate_nfo_readiness()["passed"] is True
    assert not hasattr(adapter, "place_limit_buy")


def test_sandbox_roundtrip_uses_only_sandbox_client_and_v3_commands():
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path, request.url.query.decode()))
        return httpx.Response(200, json={"status": "success", "data": {"order_id": "S-1"}})
    http = httpx.Client(base_url="https://sandbox.test", transport=httpx.MockTransport(handler))
    adapter = UpstoxSandboxOrderClient("sandbox-secret", confirmation="SANDBOX_ONLY", client=http)
    intent = SandboxOrderIntent("t", "v", "2026-10-04", "BULLISH", "CE", "NSE_FO|1", 75, "I", Decimal("10"))
    order_id = adapter.place_limit_buy(intent)
    adapter.modify_limit(order_id, quantity=75, price=Decimal("10.1"))
    adapter.cancel(order_id)
    assert calls == [
        ("POST", "/v3/order/place", ""),
        ("PUT", "/v3/order/modify", ""),
        ("DELETE", "/v3/order/cancel", "order_id=S-1"),
    ]


def test_sandbox_requires_explicit_confirmation():
    with pytest.raises(BrokerPreflightError, match="confirmation"):
        UpstoxSandboxOrderClient("x", confirmation="")


def test_manifest_does_not_overclaim_sandbox_fills():
    manifest = capability_manifest()
    assert manifest["live_order_endpoint_present"] is False
    assert "EXCHANGE_FILL" in manifest["not_claimed_by_sandbox"]


def test_missing_profile_token_stops_cleanly(monkeypatch):
    monkeypatch.delenv("UPSTOX_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr("market_lab.hilega_upstox_broker_preflight_v1.load_dotenv", lambda: False)
    with pytest.raises(SystemExit, match="STOP: required Upstox token is missing"):
        main(["--profile"])
