"""Hilega Upstox broker-plumbing preflight.

This module deliberately separates live read-only checks from sandbox order
commands.  It has no live order endpoint and cannot submit a live order.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

import httpx
from dotenv import load_dotenv


LIVE_API_BASE = "https://api.upstox.com"
SANDBOX_API_BASE = "https://sandbox.upstox.com"
SANDBOX_CONFIRMATION = "SANDBOX_ONLY"
MODEL = "HILEGA_UPSTOX_BROKER_PREFLIGHT_V1"


class BrokerPreflightError(RuntimeError):
    """Safe error without access tokens or full provider response bodies."""


@dataclass(frozen=True)
class SandboxOrderIntent:
    strategy_trade_id: str
    strategy_version: str
    session_date: str
    direction: str
    option_type: str
    instrument_token: str
    quantity: int
    product: str
    price: Decimal
    validity: str = "DAY"
    disclosed_quantity: int = 0
    trigger_price: Decimal = Decimal("0")

    def validate(self) -> None:
        if self.direction not in {"BULLISH", "BEARISH"}:
            raise BrokerPreflightError("direction must be BULLISH or BEARISH")
        expected = "CE" if self.direction == "BULLISH" else "PE"
        if self.option_type != expected:
            raise BrokerPreflightError(f"{self.direction} requires {expected}")
        if not self.instrument_token.startswith("NSE_FO|"):
            raise BrokerPreflightError("only an explicit NSE_FO option instrument is accepted")
        if self.quantity <= 0:
            raise BrokerPreflightError("quantity must be positive")
        if self.price <= 0:
            raise BrokerPreflightError("limit price must be positive")
        if self.product not in {"I", "D"}:
            raise BrokerPreflightError("product must be I or D")

    @property
    def tag(self) -> str:
        # Upstox tags are correlation labels, not evidence stores.
        compact = "".join(ch for ch in self.strategy_trade_id if ch.isalnum() or ch in "-_" )
        return f"HIL-{compact}"[:40]

    def place_payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "quantity": self.quantity,
            "product": self.product,
            "validity": self.validity,
            "price": float(self.price),
            "tag": self.tag,
            "instrument_token": self.instrument_token,
            "order_type": "LIMIT",
            "transaction_type": "BUY",
            "disclosed_quantity": self.disclosed_quantity,
            "trigger_price": float(self.trigger_price),
            "is_amo": False,
            "slice": False,
        }


class _Client:
    def __init__(self, token: str, base_url: str, client: httpx.Client | None = None):
        if not token:
            raise BrokerPreflightError("required Upstox token is missing")
        self._token = token
        self._base_url = base_url
        self._client = client or httpx.Client(base_url=base_url, timeout=15)

    def _request(self, method: str, path: str, *, json_body: dict | None = None) -> dict:
        try:
            response = self._client.request(
                method,
                path,
                json=json_body,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
        except httpx.RequestError as exc:
            raise BrokerPreflightError("Upstox network error or timeout") from exc
        if response.status_code == 429:
            raise BrokerPreflightError("Upstox rate limit reached")
        if response.status_code in {401, 403}:
            raise BrokerPreflightError("Upstox authentication or permission rejected")
        if response.status_code >= 400:
            code = None
            try:
                body = response.json()
                errors = body.get("errors") or []
                code = errors[0].get("errorCode") if errors else body.get("code")
            except (ValueError, AttributeError, IndexError):
                pass
            suffix = f" ({code})" if code else ""
            raise BrokerPreflightError(f"Upstox HTTP {response.status_code}{suffix}")
        try:
            body = response.json()
        except ValueError as exc:
            raise BrokerPreflightError("Upstox returned invalid JSON") from exc
        if not isinstance(body, dict) or body.get("status") != "success":
            raise BrokerPreflightError("Upstox returned an unsuccessful response")
        return body


class UpstoxLiveReadinessClient(_Client):
    """Read-only live-account client. No order methods are defined."""

    def __init__(self, token: str, client: httpx.Client | None = None):
        super().__init__(token, LIVE_API_BASE, client)

    def profile(self) -> dict:
        return self._request("GET", "/v2/user/profile")["data"]

    def validate_nfo_readiness(self) -> dict:
        profile = self.profile()
        exchanges = set(profile.get("exchanges") or [])
        products = set(profile.get("products") or [])
        order_types = set(profile.get("order_types") or [])
        checks = {
            "account_active": profile.get("is_active") is True,
            "nfo_enabled": "NFO" in exchanges,
            "product_available": bool(products & {"I", "D"}),
            "limit_order_available": "LIMIT" in order_types,
        }
        return {
            "model": MODEL,
            "scope": "LIVE_READ_ONLY",
            "checks": checks,
            "passed": all(checks.values()),
            "execution_enabled": False,
            "order_sent": False,
        }


class UpstoxSandboxOrderClient(_Client):
    """Sandbox-only place/modify/cancel adapter with explicit arming."""

    def __init__(self, token: str, *, confirmation: str, client: httpx.Client | None = None):
        if confirmation != SANDBOX_CONFIRMATION:
            raise BrokerPreflightError("sandbox confirmation missing")
        super().__init__(token, SANDBOX_API_BASE, client)

    def place_limit_buy(self, intent: SandboxOrderIntent) -> str:
        body = self._request("POST", "/v3/order/place", json_body=intent.place_payload())
        order_id = (body.get("data") or {}).get("order_id")
        if not order_id:
            raise BrokerPreflightError("sandbox place response has no order_id")
        return str(order_id)

    def modify_limit(self, order_id: str, *, quantity: int, price: Decimal) -> str:
        if not order_id or quantity <= 0 or price <= 0:
            raise BrokerPreflightError("invalid sandbox modify request")
        body = self._request("PUT", "/v3/order/modify", json_body={
            "quantity": quantity,
            "validity": "DAY",
            "price": float(price),
            "order_id": order_id,
            "order_type": "LIMIT",
            "disclosed_quantity": 0,
            "trigger_price": 0,
        })
        return str((body.get("data") or {}).get("order_id") or order_id)

    def cancel(self, order_id: str) -> str:
        if not order_id:
            raise BrokerPreflightError("sandbox order_id is required")
        body = self._request("DELETE", f"/v3/order/cancel?order_id={order_id}")
        return str((body.get("data") or {}).get("order_id") or order_id)


def capability_manifest() -> dict:
    return {
        "model": MODEL,
        "verified_sandbox_commands": [
            "PLACE_ORDER", "PLACE_ORDER_V3", "PLACE_MULTI_ORDER",
            "MODIFY_ORDER", "MODIFY_ORDER_V3", "CANCEL_ORDER", "CANCEL_ORDER_V3",
        ],
        "not_claimed_by_sandbox": [
            "EXCHANGE_FILL", "ORDER_BOOK_RECONCILIATION", "POSITIONS",
            "PORTFOLIO_STREAM", "REAL_FILL_LATENCY",
        ],
        "live_read_only_checks": ["PROFILE", "NFO", "PRODUCT", "LIMIT_ORDER"],
        "live_order_endpoint_present": False,
        "execution_enabled": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hilega Upstox broker preflight")
    parser.add_argument("--profile", action="store_true", help="run live read-only profile checks")
    parser.add_argument("--sandbox-roundtrip", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--trade-id")
    parser.add_argument("--session-date")
    parser.add_argument("--direction", choices=["BULLISH", "BEARISH"])
    parser.add_argument("--instrument-token")
    parser.add_argument("--quantity", type=int)
    parser.add_argument("--price", type=Decimal)
    parser.add_argument("--product", choices=["I", "D"], default="I")
    return parser


def main(argv: list[str] | None = None) -> int:
    # Match the repository services: local credentials live in .env and are
    # never accepted as CLI arguments or printed in audit output.
    load_dotenv()
    args = _parser().parse_args(argv)
    try:
        if args.profile:
            token = os.getenv("UPSTOX_ACCESS_TOKEN", "")
            print(json.dumps(UpstoxLiveReadinessClient(token).validate_nfo_readiness(), indent=2))
            return 0
        if args.sandbox_roundtrip:
            missing = [name for name in ("trade_id", "session_date", "direction", "instrument_token", "quantity", "price") if getattr(args, name) in (None, "")]
            if missing:
                raise BrokerPreflightError(f"missing arguments: {', '.join(missing)}")
            intent = SandboxOrderIntent(
                strategy_trade_id=args.trade_id,
                strategy_version="HILEGA_BROKER_TEST_V1",
                session_date=args.session_date,
                direction=args.direction,
                option_type="CE" if args.direction == "BULLISH" else "PE",
                instrument_token=args.instrument_token,
                quantity=args.quantity,
                product=args.product,
                price=args.price,
            )
            client = UpstoxSandboxOrderClient(
                os.getenv("UPSTOX_SANDBOX_ACCESS_TOKEN", ""), confirmation=args.confirm
            )
            order_id = client.place_limit_buy(intent)
            modified_id = client.modify_limit(order_id, quantity=intent.quantity, price=intent.price)
            cancelled_id = client.cancel(modified_id)
            print(json.dumps({
                "model": MODEL,
                "scope": "UPSTOX_SANDBOX",
                "intent": {**asdict(intent), "price": str(intent.price), "trigger_price": str(intent.trigger_price)},
                "order_id": order_id,
                "modified_order_id": modified_id,
                "cancelled_order_id": cancelled_id,
                "live_order_sent": False,
            }, indent=2))
            return 0
    except BrokerPreflightError as exc:
        raise SystemExit(f"STOP: {exc}") from None
    print(json.dumps(capability_manifest(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
