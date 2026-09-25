from __future__ import annotations

import fcntl
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

MODEL = "LIVE_SHADOW_STEP_AUDIT_V1"


@dataclass(frozen=True)
class StepAuditRecord:
    sequence: int
    event_time: str
    checkpoint: str | None
    observation_id: str | None
    stage: str
    status: str
    payload: dict[str, Any]
    previous_hash: str | None
    record_hash: str


class ShadowStepAuditStoreV1:
    """Append-only hash-chained audit for every live-shadow processing step."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _canonical(data: dict[str, Any]) -> bytes:
        return json.dumps(
            data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
        ).encode("utf-8")

    @staticmethod
    def _read_all_from_handle(handle) -> list[dict[str, Any]]:
        handle.seek(0)
        rows = []
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

        with self.path.open("r", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
            try:
                return self._read_all_from_handle(handle)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def append(
        self,
        *,
        event_time: datetime,
        checkpoint: datetime | None,
        stage: str,
        status: str,
        payload: dict[str, Any] | None = None,
        observation_id: str | None = None,
    ) -> StepAuditRecord:
        # Sequence allocation, previous-hash lookup, hash calculation and
        # append must happen under one inter-process exclusive lock.
        with self.path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                rows = self._read_all_from_handle(handle)
                previous_hash = rows[-1]["record_hash"] if rows else None

                core = {
                    "model": MODEL,
                    "sequence": len(rows) + 1,
                    "event_time": event_time.isoformat(),
                    "checkpoint": checkpoint.isoformat() if checkpoint else None,
                    "observation_id": observation_id,
                    "stage": stage,
                    "status": status,
                    "payload": payload or {},
                    "previous_hash": previous_hash,
                }

                record_hash = hashlib.sha256(
                    self._canonical(core)
                ).hexdigest()

                record = {
                    **core,
                    "record_hash": record_hash,
                }

                handle.seek(0, os.SEEK_END)
                handle.write(
                    json.dumps(
                        record,
                        sort_keys=True,
                        default=str,
                    )
                    + "\n"
                )
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

        return StepAuditRecord(
            sequence=record["sequence"],
            event_time=record["event_time"],
            checkpoint=record["checkpoint"],
            observation_id=record["observation_id"],
            stage=record["stage"],
            status=record["status"],
            payload=record["payload"],
            previous_hash=record["previous_hash"],
            record_hash=record["record_hash"],
        )

    def verify_chain(self) -> tuple[bool, str | None]:
        previous_hash = None
        for expected_sequence, row in enumerate(self.read_all(), start=1):
            if row.get("sequence") != expected_sequence:
                return False, f"sequence mismatch at {expected_sequence}"
            if row.get("previous_hash") != previous_hash:
                return False, f"previous_hash mismatch at {expected_sequence}"
            core = {k: v for k, v in row.items() if k != "record_hash"}
            expected_hash = hashlib.sha256(self._canonical(core)).hexdigest()
            if expected_hash != row.get("record_hash"):
                return False, f"hash mismatch at {expected_sequence}"
            previous_hash = row["record_hash"]
        return True, None


def normalized_checkpoint_payload(cp) -> dict[str, Any]:
    horizons = {}
    for feature in cp.features:
        horizons[f"{feature.horizon_minutes}m"] = {
            "state": feature.state,
            "current_ce_oi": feature.current_ce_oi,
            "current_pe_oi": feature.current_pe_oi,
            "prior_ce_oi": feature.prior_ce_oi,
            "prior_pe_oi": feature.prior_pe_oi,
            "ce_delta": feature.ce_delta,
            "pe_delta": feature.pe_delta,
            "imbalance": feature.imbalance,
            "prior_pcr": feature.prior_pcr,
            "current_pcr": feature.current_pcr,
            "pcr_change": feature.pcr_change,
        }
    return {
        "session_date": cp.session_date,
        "spot": cp.spot,
        "moving_atm": cp.moving_atm,
        "moving_strikes": list(cp.moving_strikes),
        "all3_state": cp.all3_state,
        "previous_directional_all3": cp.previous_directional_all3,
        "state_5m": cp.state_5m,
        "state_10m": cp.state_10m,
        "state_15m": cp.state_15m,
        "ce_instrument_key": cp.ce_instrument_key,
        "pe_instrument_key": cp.pe_instrument_key,
        "health_state": cp.health_state,
        "health_allowed": cp.health_allowed,
        "health_reason": cp.health_reason,
        "source_received_at": cp.source_received_at.isoformat(),
        "source_delay_ms": cp.source_delay_ms,
        "horizons": horizons,
    }
