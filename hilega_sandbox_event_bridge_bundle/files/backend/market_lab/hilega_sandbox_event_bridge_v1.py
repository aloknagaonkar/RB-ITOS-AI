from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from filelock import FileLock

from .hilega_directional_coordinator_v1 import (
    BEARISH_ENTRY_EVENTS,
    BEARISH_EXIT_EVENTS,
    BULLISH_ENTRY_EVENTS,
    BULLISH_EXIT_EVENTS,
)
from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1


MODEL = "HILEGA_SANDBOX_EVENT_BRIDGE_V1"
DEFAULT_SOURCE = Path("data/live-observation/hilega-directional-v1/step-audit.jsonl")
DEFAULT_OUTPUT = Path("data/live-observation/hilega-upstox-sandbox-v1/would-submit.jsonl")

EVENT_DIRECTION = {
    **{name: "BULLISH" for name in BULLISH_ENTRY_EVENTS | BULLISH_EXIT_EVENTS},
    **{name: "BEARISH" for name in BEARISH_ENTRY_EVENTS | BEARISH_EXIT_EVENTS},
}
ENTRY_EVENTS = BULLISH_ENTRY_EVENTS | BEARISH_ENTRY_EVENTS
EXIT_EVENTS = BULLISH_EXIT_EVENTS | BEARISH_EXIT_EVENTS


class BridgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class BridgeConfig:
    enabled: bool
    source: Path
    output: Path

    @classmethod
    def from_env(cls, env_path: str | Path = ".env") -> "BridgeConfig":
        values = dotenv_values(env_path)

        def value(name: str, default: str) -> str:
            return str(os.getenv(name, values.get(name, default) or default)).strip()

        return cls(
            enabled=value("HILEGA_SANDBOX_BRIDGE_OBSERVATION_ENABLED", "0") == "1",
            source=Path(value("HILEGA_SANDBOX_BRIDGE_SOURCE", str(DEFAULT_SOURCE))),
            output=Path(value("HILEGA_SANDBOX_BRIDGE_OUTPUT", str(DEFAULT_OUTPUT))),
        )


class IntentStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = FileLock(str(path) + ".lock")

    def rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def append(self, row: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _timestamp(record: dict[str, Any]) -> str:
    payload = record.get("payload") or {}
    candidate = (
        record.get("checkpoint")
        or payload.get("bar_timestamp")
        or payload.get("cutoff_timestamp")
        or record.get("event_time")
    )
    if not candidate:
        raise BridgeError("recognized event has no causal timestamp")
    datetime.fromisoformat(str(candidate))
    return str(candidate)


def _trade_id(direction: str, timestamp: str, record_hash: str) -> str:
    local = datetime.fromisoformat(timestamp)
    stamp = local.strftime("%Y%m%d-%H%M")
    return f"HIL-{stamp}-{direction}-{record_hash[:8]}"


class HilegaSandboxEventBridgeV1:
    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self.source = ShadowStepAuditStoreV1(config.source)
        self.store = IntentStore(config.output)

    @staticmethod
    def _accepted_events(record: dict[str, Any]) -> list[str]:
        if record.get("stage") not in {"DIRECTIONAL_DECISION", "DIRECTIONAL_SESSION_CUTOFF"}:
            return []
        if record.get("status") not in {"PROCESSED", "PASS"}:
            return []
        events = (record.get("payload") or {}).get("accepted_events") or []
        return [str(name) for name in events if str(name) in EVENT_DIRECTION]

    @staticmethod
    def _active_trades(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        active: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row.get("decision") != "WOULD_SUBMIT":
                continue
            direction = row["direction"]
            if row["event_type"] == "ENTRY":
                active[direction] = row
            elif row["event_type"] == "EXIT":
                active.pop(direction, None)
        return active

    def run_once(self) -> dict[str, Any]:
        if not self.config.enabled:
            raise BridgeError("HILEGA_SANDBOX_BRIDGE_OBSERVATION_ENABLED is not 1")
        if not self.config.source.exists():
            raise BridgeError(f"source audit does not exist: {self.config.source}")
        valid, reason = self.source.verify_chain()
        if not valid:
            raise BridgeError(f"source audit integrity failed: {reason}")

        with self.store.lock:
            existing = self.store.rows()
            existing_ids = {row["intent_id"] for row in existing}
            active = self._active_trades(existing)
            written = 0
            ignored = 0
            blocked = 0

            for record in self.source.read_all():
                names = self._accepted_events(record)
                if not names:
                    continue
                if len(names) > 1:
                    raise BridgeError(
                        f"ambiguous accepted execution events at source sequence {record.get('sequence')}: {names}"
                    )
                name = names[0]
                intent_id = hashlib.sha256(
                    f"{record['record_hash']}|{name}".encode()
                ).hexdigest()
                if intent_id in existing_ids:
                    ignored += 1
                    continue

                direction = EVENT_DIRECTION[name]
                event_type = "ENTRY" if name in ENTRY_EVENTS else "EXIT"
                timestamp = _timestamp(record)
                open_trade = active.get(direction)

                if event_type == "ENTRY":
                    if open_trade is not None:
                        decision = "WOULD_NOT_SUBMIT"
                        reason_code = "DIRECTION_ALREADY_OPEN"
                        trade_id = open_trade["trade_id"]
                        blocked += 1
                    else:
                        decision = "WOULD_SUBMIT"
                        reason_code = "ACCEPTED_HILEGA_ENTRY"
                        trade_id = _trade_id(direction, timestamp, record["record_hash"])
                else:
                    if open_trade is None:
                        decision = "WOULD_NOT_SUBMIT"
                        reason_code = "NO_OPEN_BRIDGE_TRADE"
                        trade_id = None
                        blocked += 1
                    else:
                        decision = "WOULD_SUBMIT"
                        reason_code = "ACCEPTED_HILEGA_EXIT"
                        trade_id = open_trade["trade_id"]

                row = {
                    "model": MODEL,
                    "intent_id": intent_id,
                    "event_id": f"HILEGA-AUDIT-{record['record_hash'][:24]}-{event_type}",
                    "trade_id": trade_id,
                    "event_type": event_type,
                    "direction": direction,
                    "option_type": "CE" if direction == "BULLISH" else "PE",
                    "transaction_type": "BUY" if event_type == "ENTRY" else "SELL",
                    "event_timestamp": timestamp,
                    "source_event": name,
                    "source_sequence": record.get("sequence"),
                    "source_record_hash": record.get("record_hash"),
                    "decision": decision,
                    "reason_code": reason_code,
                    "quantity_policy": "ONE_DYNAMIC_BROKER_LOT",
                    "broker_called": False,
                    "sandbox_order_sent": False,
                    "live_order_sent": False,
                    "observation_only": True,
                }
                self.store.append(row)
                existing_ids.add(intent_id)
                written += 1
                if decision == "WOULD_SUBMIT" and event_type == "ENTRY":
                    active[direction] = row
                elif decision == "WOULD_SUBMIT" and event_type == "EXIT":
                    active.pop(direction, None)

            return {
                "model": MODEL,
                "source_rows": len(self.source.read_all()),
                "written": written,
                "idempotent_ignored": ignored,
                "blocked": blocked,
                "open_trade_ids": {key: row["trade_id"] for key, row in active.items()},
                "broker_called": False,
                "sandbox_order_sent": False,
                "live_order_sent": False,
                "observation_only": True,
                "output": str(self.config.output),
            }


def main() -> int:
    parser = argparse.ArgumentParser(description="Observation-only Hilega audit to sandbox-intent bridge")
    parser.add_argument("--once", action="store_true", required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()
    result = HilegaSandboxEventBridgeV1(BridgeConfig.from_env(args.env_file)).run_once()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
