from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .paper_canary_models import (
    PaperCanaryCircuitState,
    PaperCanaryRuntimeState,
    PaperCanaryWorkerStatus,
)


class PaperCanaryStateCorruptionError(Exception):
    pass


class PaperCanaryStateStorageError(Exception):
    pass


class PaperCanaryStateStore(Protocol):
    def load(self) -> PaperCanaryRuntimeState | None: ...
    def save(self, state: PaperCanaryRuntimeState) -> None: ...


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_time(value: object, field: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception as exc:
        raise PaperCanaryStateCorruptionError(f"invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PaperCanaryStateCorruptionError(f"naive {field}")
    return parsed


def _payload(state: PaperCanaryRuntimeState) -> dict[str, object]:
    data = asdict(state)
    data["worker_status"] = state.worker_status.value
    data["circuit_state"] = state.circuit_state.value
    for key in (
        "last_cycle_started_at",
        "last_cycle_completed_at",
        "last_successful_cycle_at",
        "next_eligible_cycle_at",
    ):
        data[key] = _iso(getattr(state, key))
    return data


def _decode(payload: dict[str, object]) -> PaperCanaryRuntimeState:
    try:
        return PaperCanaryRuntimeState(
            worker_status=PaperCanaryWorkerStatus(payload["worker_status"]),
            circuit_state=PaperCanaryCircuitState(payload["circuit_state"]),
            entry_suspended=payload["entry_suspended"],
            consecutive_failures=payload["consecutive_failures"],
            healthy_probe_cycles=payload["healthy_probe_cycles"],
            last_cycle_started_at=_parse_time(payload.get("last_cycle_started_at"), "last_cycle_started_at"),
            last_cycle_completed_at=_parse_time(payload.get("last_cycle_completed_at"), "last_cycle_completed_at"),
            last_successful_cycle_at=_parse_time(payload.get("last_successful_cycle_at"), "last_successful_cycle_at"),
            next_eligible_cycle_at=_parse_time(payload.get("next_eligible_cycle_at"), "next_eligible_cycle_at"),
            latest_reason_code=payload["latest_reason_code"],
            recovery_count=payload["recovery_count"],
            candidate_count=payload["candidate_count"],
            attempted_count=payload["attempted_count"],
            accepted_count=payload["accepted_count"],
            rejected_count=payload["rejected_count"],
            uncertain_count=payload["uncertain_count"],
            daily_action_count=payload["daily_action_count"],
            latest_execution_id=payload.get("latest_execution_id"),
            persistence_status=payload["persistence_status"],
            schema_version=payload["schema_version"],
        )
    except PaperCanaryStateCorruptionError:
        raise
    except Exception as exc:
        raise PaperCanaryStateCorruptionError("runtime state violates schema") from exc


class AtomicJsonPaperCanaryStateStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> PaperCanaryRuntimeState | None:
        if not self.path.exists():
            return None
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PaperCanaryStateStorageError("runtime state unavailable") from exc
        try:
            envelope = json.loads(raw)
            if envelope.get("schema_version") != "1.0":
                raise PaperCanaryStateCorruptionError("unsupported runtime state envelope")
            payload = envelope["payload"]
            if type(payload) is not dict:
                raise PaperCanaryStateCorruptionError("runtime state payload must be object")
            encoded = _canonical_json(payload)
            if envelope.get("payload_sha256") != _digest(encoded):
                raise PaperCanaryStateCorruptionError("runtime state digest mismatch")
            return _decode(payload)
        except PaperCanaryStateCorruptionError:
            raise
        except Exception as exc:
            raise PaperCanaryStateCorruptionError("invalid runtime state envelope") from exc

    def save(self, state: PaperCanaryRuntimeState) -> None:
        if type(state) is not PaperCanaryRuntimeState:
            raise ValueError("state must be PaperCanaryRuntimeState")
        payload = _payload(state)
        encoded = _canonical_json(payload)
        envelope = _canonical_json({
            "schema_version": "1.0",
            "payload": payload,
            "payload_sha256": _digest(encoded),
        })
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(envelope)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise PaperCanaryStateStorageError("unable to persist runtime state") from exc
