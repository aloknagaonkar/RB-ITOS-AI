from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping

POLICY_VERSION = "signal-enrichment-outcome-v1"
VALID_STATUSES = {"READY", "MISSING", "FAILED", "STALE", "NOT_APPLICABLE"}


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _text(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _outcome_id(row: Mapping[str, Any], policy_version: str) -> str:
    raw = "|".join(
        (
            str(row.get("signal_id") or "missing"),
            str(row.get("stage") or "missing"),
            str(row.get("attempt_timestamp") or "missing"),
            policy_version,
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def ensure_signal_enrichment_outcome_schema(database_path: str | Path) -> None:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_enrichment_outcomes (
                outcome_id TEXT PRIMARY KEY,
                signal_id TEXT NOT NULL,
                strategy_id TEXT,
                bundle_id TEXT,
                stage TEXT NOT NULL,
                status TEXT NOT NULL,
                reason_code TEXT,
                reason TEXT,
                input_source TEXT,
                input_cutoff_timestamp TEXT,
                latest_source_timestamp TEXT,
                no_lookahead_passed INTEGER,
                attempt_timestamp TEXT NOT NULL,
                retry_count INTEGER NOT NULL DEFAULT 0,
                final_retry_status TEXT,
                policy_version TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_signal_enrichment_outcomes_signal_stage
            ON signal_enrichment_outcomes(signal_id, stage, attempt_timestamp)
            """
        )


def persist_signal_enrichment_outcomes(
    database_path: str | Path,
    outcomes: Iterable[Mapping[str, Any]],
    *,
    policy_version: str = POLICY_VERSION,
) -> tuple[str, ...]:
    path = Path(database_path)
    ensure_signal_enrichment_outcome_schema(path)
    now = datetime.now(timezone.utc).isoformat()
    ids: list[str] = []

    with sqlite3.connect(path) as connection:
        for original in outcomes:
            row = dict(original)
            signal_id = str(row.get("signal_id") or "").strip()
            stage = str(row.get("stage") or "").strip().upper()
            status = str(row.get("status") or "MISSING").strip().upper()
            if not signal_id:
                raise ValueError("signal enrichment outcome requires signal_id")
            if not stage:
                raise ValueError("signal enrichment outcome requires stage")
            if status not in VALID_STATUSES:
                raise ValueError(f"unsupported signal enrichment status: {status}")

            attempt_timestamp = str(row.get("attempt_timestamp") or now)
            normalized = {
                **row,
                "signal_id": signal_id,
                "stage": stage,
                "status": status,
                "attempt_timestamp": attempt_timestamp,
                "policy_version": policy_version,
            }
            outcome_id = _outcome_id(normalized, policy_version)
            ids.append(outcome_id)
            no_lookahead = normalized.get("no_lookahead_passed")
            no_lookahead_db = None if no_lookahead is None else int(bool(no_lookahead))

            connection.execute(
                """
                INSERT INTO signal_enrichment_outcomes (
                    outcome_id, signal_id, strategy_id, bundle_id, stage, status,
                    reason_code, reason, input_source, input_cutoff_timestamp,
                    latest_source_timestamp, no_lookahead_passed,
                    attempt_timestamp, retry_count, final_retry_status,
                    policy_version, payload_json, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(outcome_id) DO UPDATE SET
                    status=excluded.status,
                    reason_code=excluded.reason_code,
                    reason=excluded.reason,
                    input_source=excluded.input_source,
                    input_cutoff_timestamp=excluded.input_cutoff_timestamp,
                    latest_source_timestamp=excluded.latest_source_timestamp,
                    no_lookahead_passed=excluded.no_lookahead_passed,
                    retry_count=excluded.retry_count,
                    final_retry_status=excluded.final_retry_status,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    outcome_id,
                    signal_id,
                    _text(normalized.get("strategy_id")),
                    _text(normalized.get("bundle_id")),
                    stage,
                    status,
                    _text(normalized.get("reason_code")),
                    _text(normalized.get("reason")),
                    _text(normalized.get("input_source")),
                    _text(normalized.get("input_cutoff_timestamp")),
                    _text(normalized.get("latest_source_timestamp")),
                    no_lookahead_db,
                    attempt_timestamp,
                    int(normalized.get("retry_count") or 0),
                    _text(normalized.get("final_retry_status")),
                    policy_version,
                    _json(normalized),
                    now,
                    now,
                ),
            )
    return tuple(ids)


def read_signal_enrichment_outcomes(
    database_path: str | Path,
    *,
    signal_id: str | None = None,
    stage: str | None = None,
) -> list[dict[str, Any]]:
    path = Path(database_path)
    ensure_signal_enrichment_outcome_schema(path)
    clauses: list[str] = []
    values: list[object] = []
    if signal_id:
        clauses.append("signal_id = ?")
        values.append(signal_id)
    if stage:
        clauses.append("stage = ?")
        values.append(stage.upper())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            f"""
            SELECT * FROM signal_enrichment_outcomes
            {where}
            ORDER BY attempt_timestamp, signal_id, stage
            """,
            values,
        ).fetchall()
    return [dict(row) for row in rows]


__all__ = [
    "POLICY_VERSION",
    "VALID_STATUSES",
    "ensure_signal_enrichment_outcome_schema",
    "persist_signal_enrichment_outcomes",
    "read_signal_enrichment_outcomes",
]
