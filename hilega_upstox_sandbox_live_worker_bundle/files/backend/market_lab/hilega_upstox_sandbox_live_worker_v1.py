from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from filelock import FileLock
from zoneinfo import ZoneInfo

from .hilega_sandbox_event_bridge_v1 import (
    BridgeConfig,
    HilegaSandboxEventBridgeV1,
    IntentStore,
)
from .live_shadow_step_audit_v1 import ShadowStepAuditStoreV1
from .hilega_upstox_sandbox_execution_v1 import (
    HilegaExecutionEvent,
    HilegaSandboxExecutor,
    JsonlJournal,
    SandboxConfig,
    UpstoxTransport,
)


MODEL = "HILEGA_UPSTOX_SANDBOX_LIVE_WORKER_V1"
IST = ZoneInfo("Asia/Kolkata")
DEFAULT_CONTROL = Path("data/live-observation/hilega-upstox-sandbox-v1/live-control.json")
DEFAULT_DISPATCH = Path("data/live-observation/hilega-upstox-sandbox-v1/live-dispatch.jsonl")
DEFAULT_PID = Path("data/hilega-upstox-sandbox-worker.pid")


class LiveWorkerError(RuntimeError):
    pass


@dataclass(frozen=True)
class LiveWorkerPaths:
    control: Path = DEFAULT_CONTROL
    dispatch: Path = DEFAULT_DISPATCH


class JsonControl:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = FileLock(str(path) + ".lock")

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "model": MODEL,
                "armed": False,
                "kill_switch": True,
                "sandbox_only": True,
                "live_execution_enabled": False,
            }
        return json.loads(self.path.read_text())

    def write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with self.lock:
            temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            os.replace(temporary, self.path)


class DispatchStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = FileLock(str(path) + ".lock")

    def rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def append(self, row: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")

    def terminal_intent_ids(self) -> set[str]:
        return {str(row["intent_id"]) for row in self.rows() if row.get("terminal")}

    def accepted_orders(self, session_date: str) -> list[dict[str, Any]]:
        return [
            row for row in self.rows()
            if row.get("session_date") == session_date
            and row.get("status") == "ACCEPTED"
            and row.get("terminal") is True
        ]

    def open_trade(self, session_date: str) -> dict[str, Any] | None:
        active: dict[str, dict[str, Any]] = {}
        for row in self.accepted_orders(session_date):
            if row["event_type"] == "ENTRY":
                active[row["trade_id"]] = row
            elif row["event_type"] == "EXIT":
                active.pop(row["trade_id"], None)
        if len(active) > 1:
            raise LiveWorkerError(f"dispatch contains multiple open trades: {sorted(active)}")
        return next(iter(active.values()), None)


def max_source_sequence(source: Path) -> int:
    if not source.exists():
        return 0
    maximum = 0
    for line in source.read_text().splitlines():
        if line.strip():
            maximum = max(maximum, int(json.loads(line).get("sequence") or 0))
    return maximum


def arm_session(
    *,
    session_date: date,
    source: Path,
    control: JsonControl,
    max_orders: int,
    confirmation: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    if confirmation != "ARM_UPSTOX_SANDBOX_ONLY":
        raise LiveWorkerError("explicit --confirm ARM_UPSTOX_SANDBOX_ONLY is required")
    current = (now or datetime.now(IST)).astimezone(IST).date()
    if session_date < current:
        raise LiveWorkerError("cannot arm a historical session")
    if session_date > current + timedelta(days=7):
        raise LiveWorkerError("session may be armed at most seven days ahead")
    if max_orders < 2 or max_orders > 20:
        raise LiveWorkerError("max orders must be between 2 and 20")
    if source.exists():
        valid, reason = ShadowStepAuditStoreV1(source).verify_chain()
        if not valid:
            raise LiveWorkerError(f"cannot arm: source audit integrity failed: {reason}")
    payload = {
        "model": MODEL,
        "armed": True,
        "kill_switch": False,
        "session_date": session_date.isoformat(),
        "baseline_source_sequence": max_source_sequence(source),
        "max_orders": max_orders,
        "sandbox_only": True,
        "live_execution_enabled": False,
        "armed_at": (now or datetime.now(IST)).astimezone(IST).isoformat(),
    }
    control.write(payload)
    return payload


def disarm(control: JsonControl) -> dict[str, Any]:
    payload = control.read()
    payload.update(
        {
            "armed": False,
            "kill_switch": True,
            "live_execution_enabled": False,
            "disarmed_at": datetime.now(IST).isoformat(),
        }
    )
    control.write(payload)
    return payload


class HilegaUpstoxSandboxLiveWorkerV1:
    def __init__(
        self,
        *,
        paths: LiveWorkerPaths = LiveWorkerPaths(),
        env_file: Path = Path(".env"),
        now_fn: Callable[[], datetime] | None = None,
        executor_factory: Callable[[SandboxConfig], HilegaSandboxExecutor] | None = None,
    ) -> None:
        self.paths = paths
        self.control = JsonControl(paths.control)
        self.dispatch = DispatchStore(paths.dispatch)
        self.env_file = env_file
        self.now_fn = now_fn or (lambda: datetime.now(IST))
        self.executor_factory = executor_factory or self._real_executor

    def _real_executor(self, config: SandboxConfig) -> HilegaSandboxExecutor:
        return HilegaSandboxExecutor(
            config,
            UpstoxTransport(config.analytics_token, config.sandbox_token),
            JsonlJournal(config.journal_path),
        )

    @staticmethod
    def _event(intent: dict[str, Any]) -> HilegaExecutionEvent:
        return HilegaExecutionEvent(
            event_id=str(intent["event_id"]),
            trade_id=str(intent["trade_id"]),
            event_type=str(intent["event_type"]),
            direction=str(intent["direction"]),
            event_timestamp=str(intent["event_timestamp"]),
            strategy_id="HILEGA_DIRECTIONAL_SHADOW_V1",
        )

    def _engage_kill_switch(self, control: dict[str, Any], reason: str) -> None:
        control.update(
            {
                "armed": False,
                "kill_switch": True,
                "failure_reason": reason,
                "failed_at": self.now_fn().astimezone(IST).isoformat(),
                "live_execution_enabled": False,
            }
        )
        self.control.write(control)

    def run_once(self) -> dict[str, Any]:
        control = self.control.read()
        if not control.get("armed") or control.get("kill_switch"):
            return self._summary(control, "DISARMED", 0, 0)
        session_date = str(control.get("session_date") or "")
        now = self.now_fn().astimezone(IST)
        if now.date().isoformat() != session_date:
            return self._summary(control, "WAITING_FOR_ARMED_SESSION", 0, 0)

        sandbox = SandboxConfig.from_env(self.env_file)
        try:
            sandbox.assert_ready("SANDBOX_ONLY")
        except Exception as exc:
            self._engage_kill_switch(control, f"SANDBOX_CONFIG_INVALID:{exc}")
            raise LiveWorkerError(str(exc)) from exc

        bridge = HilegaSandboxEventBridgeV1(
            BridgeConfig(True, Path(os.getenv("HILEGA_SANDBOX_BRIDGE_SOURCE", str(DEFAULT_SOURCE))),
                         Path(os.getenv("HILEGA_SANDBOX_BRIDGE_OUTPUT", str(DEFAULT_OUTPUT))))
        )
        bridge_result = bridge.run_once()
        intents = IntentStore(bridge.config.output).rows()
        terminal = self.dispatch.terminal_intent_ids()
        eligible = [
            row for row in intents
            if row.get("decision") == "WOULD_SUBMIT"
            and str(row.get("event_timestamp", ""))[:10] == session_date
            and int(row.get("source_sequence") or 0) > int(control["baseline_source_sequence"])
            and row["intent_id"] not in terminal
        ]
        eligible.sort(key=lambda row: (int(row["source_sequence"]), row["intent_id"]))

        sent = 0
        skipped = 0
        executor = self.executor_factory(sandbox)
        for intent in eligible:
            accepted = self.dispatch.accepted_orders(session_date)
            if len(accepted) >= int(control["max_orders"]):
                self._engage_kill_switch(control, "SESSION_ORDER_LIMIT_REACHED")
                raise LiveWorkerError("session order limit reached")
            open_trade = self.dispatch.open_trade(session_date)
            if intent["event_type"] == "ENTRY" and open_trade is not None:
                self._engage_kill_switch(control, "OVERLAPPING_ENTRY_BLOCKED")
                raise LiveWorkerError("entry blocked because a trade is already open")
            if intent["event_type"] == "EXIT" and (
                open_trade is None or open_trade["trade_id"] != intent["trade_id"]
            ):
                self._engage_kill_switch(control, "UNMATCHED_EXIT_BLOCKED")
                raise LiveWorkerError("exit does not match the single open trade")
            try:
                result = executor.process(self._event(intent), "SANDBOX_ONLY")
            except Exception as exc:
                self.dispatch.append(
                    {
                        "model": MODEL,
                        "intent_id": intent["intent_id"],
                        "trade_id": intent["trade_id"],
                        "event_type": intent["event_type"],
                        "session_date": session_date,
                        "status": "FAILED",
                        "terminal": False,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "sandbox_only": True,
                        "live_order_sent": False,
                        "timestamp": now.isoformat(),
                    }
                )
                self._engage_kill_switch(control, f"BROKER_SUBMISSION_FAILED:{type(exc).__name__}")
                raise
            self.dispatch.append(
                {
                    "model": MODEL,
                    "intent_id": intent["intent_id"],
                    "event_id": intent["event_id"],
                    "trade_id": intent["trade_id"],
                    "event_type": intent["event_type"],
                    "direction": intent["direction"],
                    "session_date": session_date,
                    "source_sequence": intent["source_sequence"],
                    "status": "ACCEPTED",
                    "terminal": True,
                    "broker_order_id": result["broker_order_id"],
                    "instrument_key": result["contract"]["instrument_key"],
                    "option_type": result["contract"]["option_type"],
                    "quantity": result["quantity"],
                    "transaction_type": result["transaction_type"],
                    "sandbox_only": True,
                    "live_order_sent": False,
                    "timestamp": now.isoformat(),
                }
            )
            sent += 1
        return {
            **self._summary(control, "PROCESSED", sent, skipped),
            "bridge": bridge_result,
        }

    def _summary(self, control: dict[str, Any], status: str, sent: int, skipped: int) -> dict[str, Any]:
        session_date = str(control.get("session_date") or "")
        accepted = self.dispatch.accepted_orders(session_date) if session_date else []
        return {
            "model": MODEL,
            "status": status,
            "armed": bool(control.get("armed")),
            "kill_switch": bool(control.get("kill_switch", True)),
            "session_date": session_date or None,
            "baseline_source_sequence": control.get("baseline_source_sequence"),
            "orders_sent_this_run": sent,
            "skipped_this_run": skipped,
            "accepted_orders_this_session": len(accepted),
            "open_trade_id": (self.dispatch.open_trade(session_date) or {}).get("trade_id") if session_date else None,
            "sandbox_only": True,
            "live_execution_enabled": False,
            "live_order_sent": False,
        }


# Imported after class declarations to keep the bridge defaults authoritative.
from .hilega_sandbox_event_bridge_v1 import DEFAULT_OUTPUT, DEFAULT_SOURCE  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Session-armed Hilega -> Upstox Sandbox worker")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--arm-session", type=date.fromisoformat)
    actions.add_argument("--disarm", action="store_true")
    actions.add_argument("--once", action="store_true")
    actions.add_argument("--serve", action="store_true")
    actions.add_argument("--status", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--max-orders", type=int, default=10)
    parser.add_argument("--interval-seconds", type=int, default=10)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()

    paths = LiveWorkerPaths()
    control = JsonControl(paths.control)
    if args.arm_session:
        source = Path(os.getenv("HILEGA_SANDBOX_BRIDGE_SOURCE", str(DEFAULT_SOURCE)))
        result = arm_session(
            session_date=args.arm_session,
            source=source,
            control=control,
            max_orders=args.max_orders,
            confirmation=args.confirm,
        )
    elif args.disarm:
        result = disarm(control)
    elif args.status:
        worker = HilegaUpstoxSandboxLiveWorkerV1(paths=paths, env_file=args.env_file)
        result = worker._summary(control.read(), "STATUS", 0, 0)
    elif args.once:
        result = HilegaUpstoxSandboxLiveWorkerV1(paths=paths, env_file=args.env_file).run_once()
    else:
        if not 2 <= args.interval_seconds <= 60:
            raise SystemExit("interval must be between 2 and 60 seconds")
        worker = HilegaUpstoxSandboxLiveWorkerV1(paths=paths, env_file=args.env_file)
        while True:
            result = worker.run_once()
            print(json.dumps(result, sort_keys=True), flush=True)
            time.sleep(args.interval_seconds)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
