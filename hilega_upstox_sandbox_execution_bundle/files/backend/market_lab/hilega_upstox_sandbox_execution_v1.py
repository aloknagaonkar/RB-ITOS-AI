from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values
from filelock import FileLock


MODEL = "HILEGA_UPSTOX_SANDBOX_EXECUTION_V1"
ANALYTICS_BASE = "https://api.upstox.com"
SANDBOX_BASE = "https://api-sandbox.upstox.com"
UNDERLYING = "NSE_INDEX|Nifty 50"
DEFAULT_JOURNAL = Path("data/live-observation/hilega-upstox-sandbox-v1/events.jsonl")


class SandboxExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class HilegaExecutionEvent:
    event_id: str
    trade_id: str
    event_type: str
    direction: str
    event_timestamp: str
    strategy_id: str = "HILEGA_DIRECTIONAL_SHADOW_V1"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "HilegaExecutionEvent":
        event = cls(**{key: raw[key] for key in cls.__dataclass_fields__ if key in raw})
        if not event.event_id.strip() or not event.trade_id.strip():
            raise SandboxExecutionError("event_id and trade_id are required")
        if event.event_type not in {"ENTRY", "EXIT"}:
            raise SandboxExecutionError("event_type must be ENTRY or EXIT")
        if event.direction not in {"BULLISH", "BEARISH"}:
            raise SandboxExecutionError("direction must be BULLISH or BEARISH")
        datetime.fromisoformat(event.event_timestamp)
        return event


@dataclass(frozen=True)
class SandboxConfig:
    enabled: bool
    kill_switch: bool
    lots: int
    max_orders_per_session: int
    analytics_token: str
    sandbox_token: str
    journal_path: Path

    @classmethod
    def from_env(cls, env_path: str | Path = ".env") -> "SandboxConfig":
        file_values = dotenv_values(env_path)

        def value(name: str, default: str = "") -> str:
            return str(os.getenv(name, file_values.get(name, default) or default)).strip()

        return cls(
            enabled=value("HILEGA_UPSTOX_SANDBOX_ENABLED", "0") == "1",
            kill_switch=value("HILEGA_UPSTOX_SANDBOX_KILL_SWITCH", "1") != "0",
            lots=int(value("HILEGA_UPSTOX_SANDBOX_LOTS", "1")),
            max_orders_per_session=int(value("HILEGA_UPSTOX_SANDBOX_MAX_ORDERS", "20")),
            analytics_token=value("UPSTOX_ACCESS_TOKEN"),
            sandbox_token=value("UPSTOX_SANDBOX_ACCESS_TOKEN"),
            journal_path=Path(value("HILEGA_UPSTOX_SANDBOX_JOURNAL", str(DEFAULT_JOURNAL))),
        )

    def assert_ready(self, confirmation: str) -> None:
        if confirmation != "SANDBOX_ONLY":
            raise SandboxExecutionError("explicit --confirm SANDBOX_ONLY is required")
        if not self.enabled:
            raise SandboxExecutionError("HILEGA_UPSTOX_SANDBOX_ENABLED is not 1")
        if self.kill_switch:
            raise SandboxExecutionError("sandbox kill switch is active")
        if self.lots != 1:
            raise SandboxExecutionError("V1 permits exactly one lot")
        if self.max_orders_per_session < 1:
            raise SandboxExecutionError("max orders per session must be positive")
        if not self.analytics_token or not self.sandbox_token:
            raise SandboxExecutionError("analytics and sandbox tokens are required")


class JsonlJournal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = FileLock(str(path) + ".lock")

    def rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def append(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")

    def event_result(self, event_id: str) -> dict[str, Any] | None:
        matches = [row for row in self.rows() if row.get("event_id") == event_id and row.get("terminal")]
        return matches[-1] if matches else None

    def event_rows(self, event_id: str) -> list[dict[str, Any]]:
        return [row for row in self.rows() if row.get("event_id") == event_id]

    def open_trade(self, trade_id: str) -> dict[str, Any] | None:
        rows = [row for row in self.rows() if row.get("trade_id") == trade_id and row.get("terminal")]
        entries = [row for row in rows if row.get("event_type") == "ENTRY" and row.get("status") == "ACCEPTED"]
        exits = [row for row in rows if row.get("event_type") == "EXIT" and row.get("status") == "ACCEPTED"]
        return entries[-1] if entries and len(entries) > len(exits) else None


class UpstoxTransport:
    def __init__(self, analytics_token: str, sandbox_token: str) -> None:
        self.analytics = httpx.Client(
            base_url=ANALYTICS_BASE,
            headers={"Authorization": f"Bearer {analytics_token}", "Accept": "application/json"},
            timeout=30,
        )
        self.sandbox = httpx.Client(
            base_url=SANDBOX_BASE,
            headers={
                "Authorization": f"Bearer {sandbox_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30,
        )

    @staticmethod
    def _body(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise SandboxExecutionError("provider returned invalid JSON") from exc
        if not response.is_success or body.get("status") != "success":
            errors = body.get("errors") or []
            safe = [{"code": x.get("errorCode"), "message": x.get("message")} for x in errors]
            raise SandboxExecutionError(f"provider rejected request: {safe}")
        return body

    def resolve_atm(self, direction: str, session_date: date) -> dict[str, Any]:
        ltp = self._body(self.analytics.get("/v3/market-quote/ltp", params={"instrument_key": UNDERLYING}))
        spot = float(next(iter(ltp["data"].values()))["last_price"])
        contracts = self._body(
            self.analytics.get("/v2/option/contract", params={"instrument_key": UNDERLYING})
        )["data"]
        future = [row for row in contracts if row.get("expiry", "") >= session_date.isoformat()]
        if not future:
            raise SandboxExecutionError("no non-expired option contracts returned")
        expiry = min(row["expiry"] for row in future)
        option_type = "CE" if direction == "BULLISH" else "PE"
        side = [row for row in future if row["expiry"] == expiry and row["instrument_type"] == option_type]
        selected = min(side, key=lambda row: (abs(float(row["strike_price"]) - spot), float(row["strike_price"])))
        return {
            "spot": spot,
            "expiry": expiry,
            "strike": float(selected["strike_price"]),
            "option_type": option_type,
            "instrument_key": selected["instrument_key"],
            "lot_size": int(selected["lot_size"]),
        }

    def place_market(self, *, instrument_key: str, quantity: int, transaction_type: str, tag: str) -> str:
        body = self._body(
            self.sandbox.post(
                "/v3/order/place",
                json={
                    "quantity": quantity,
                    "product": "I",
                    "validity": "DAY",
                    "price": 0,
                    "tag": tag[:40],
                    "instrument_token": instrument_key,
                    "order_type": "MARKET",
                    "transaction_type": transaction_type,
                    "disclosed_quantity": 0,
                    "trigger_price": 0,
                    "is_amo": False,
                    "slice": False,
                },
            )
        )
        order_ids = (body.get("data") or {}).get("order_ids") or []
        if len(order_ids) != 1:
            raise SandboxExecutionError(f"expected one broker order id, received {order_ids}")
        return str(order_ids[0])


class HilegaSandboxExecutor:
    def __init__(self, config: SandboxConfig, transport: UpstoxTransport, journal: JsonlJournal) -> None:
        self.config = config
        self.transport = transport
        self.journal = journal

    @staticmethod
    def tag(event: HilegaExecutionEvent) -> str:
        digest = hashlib.sha256(f"{event.trade_id}|{event.event_id}".encode()).hexdigest()[:16]
        return f"HIL_{event.event_type}_{digest}"

    def process(self, event: HilegaExecutionEvent, confirmation: str) -> dict[str, Any]:
        self.config.assert_ready(confirmation)
        execution_lock = FileLock(str(self.config.journal_path) + ".executor.lock")
        with execution_lock:
            return self._process_locked(event)

    def _process_locked(self, event: HilegaExecutionEvent) -> dict[str, Any]:
        prior = self.journal.event_result(event.event_id)
        if prior:
            return {**prior, "idempotent_replay": True}
        if self.journal.event_rows(event.event_id):
            raise SandboxExecutionError(
                "event has a non-terminal broker request; reconcile it before any retry"
            )

        session_date = datetime.fromisoformat(event.event_timestamp).date()
        session_rows = [row for row in self.journal.rows() if row.get("session_date") == session_date.isoformat()]
        if sum(row.get("status") == "ACCEPTED" for row in session_rows) >= self.config.max_orders_per_session:
            raise SandboxExecutionError("session order limit reached")

        open_entry = self.journal.open_trade(event.trade_id)
        if event.event_type == "ENTRY":
            if open_entry:
                raise SandboxExecutionError("trade already has an accepted entry")
            contract = self.transport.resolve_atm(event.direction, session_date)
            quantity = contract["lot_size"] * self.config.lots
            side = "BUY"
        else:
            if not open_entry:
                raise SandboxExecutionError("exit rejected: no accepted open entry for trade_id")
            contract = open_entry["contract"]
            quantity = int(open_entry["quantity"])
            side = "SELL"

        requested = {
            "model": MODEL,
            **asdict(event),
            "session_date": session_date.isoformat(),
            "event_type": event.event_type,
            "status": "REQUESTED",
            "terminal": False,
            "contract": contract,
            "quantity": quantity,
            "transaction_type": side,
            "sandbox_only": True,
            "live_execution_enabled": False,
        }
        self.journal.append(requested)

        # A REQUESTED row without a terminal row is intentionally not retried.
        # It requires operator reconciliation because the broker may have accepted it.
        order_id = self.transport.place_market(
            instrument_key=contract["instrument_key"],
            quantity=quantity,
            transaction_type=side,
            tag=self.tag(event),
        )
        result = {
            **requested,
            "status": "ACCEPTED",
            "terminal": True,
            "broker_order_id": order_id,
            "idempotent_replay": False,
        }
        self.journal.append(result)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Explicit Hilega -> Upstox Sandbox event adapter")
    parser.add_argument("--event-json", type=Path, required=True)
    parser.add_argument("--confirm", default="")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()

    config = SandboxConfig.from_env(args.env_file)
    event = HilegaExecutionEvent.from_dict(json.loads(args.event_json.read_text()))
    transport = UpstoxTransport(config.analytics_token, config.sandbox_token)
    result = HilegaSandboxExecutor(config, transport, JsonlJournal(config.journal_path)).process(
        event, args.confirm
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
