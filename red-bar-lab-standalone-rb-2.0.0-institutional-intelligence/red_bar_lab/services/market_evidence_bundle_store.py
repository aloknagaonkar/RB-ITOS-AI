from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

POLICY_VERSION = "market-evidence-v5"


def _json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _bundle_id(underlying_name: str, view: Mapping[str, Any]) -> str:
    """Identify one aligned source observation, not one monitor cycle.

    Collection time is intentionally excluded. Re-reading the same underlying,
    futures and option observations resolves to the same immutable bundle.
    """
    anchors = (
        view.get("underlying_bar_close_timestamp")
        or view.get("underlying_timestamp"),
        view.get("futures_bar_close_timestamp")
        or view.get("futures_market_timestamp"),
        view.get("option_timestamp"),
    )
    if not any(anchors):
        anchors = (view.get("as_of_timestamp") or "missing",)
    raw = "|".join(
        [str(underlying_name), POLICY_VERSION]
        + [str(value or "missing") for value in anchors]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_evidence_bundles (
            bundle_id TEXT PRIMARY KEY,
            underlying_name TEXT NOT NULL,
            as_of_timestamp TEXT NOT NULL,
            underlying_timestamp TEXT,
            futures_market_timestamp TEXT,
            futures_collection_timestamp TEXT,
            option_timestamp TEXT,
            observed_direction TEXT,
            structural_state TEXT,
            direction_state TEXT,
            evidence_readiness TEXT,
            contract_quality TEXT,
            trade_eligibility TEXT,
            trade_bias TEXT,
            blocking_reasons_json TEXT NOT NULL,
            caution_reasons_json TEXT NOT NULL,
            policy_version TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_market_evidence_latest
        ON market_evidence_bundles(underlying_name, as_of_timestamp DESC)
        """
    )


def persist_market_evidence_bundle(
    database_path: str | Path,
    *,
    underlying_name: str,
    view: Mapping[str, Any],
) -> str:
    """Persist one immutable bundle for an aligned source observation.

    Reprocessing an identical evidence identity is idempotent. The original
    payload and creation timestamp are retained for auditability.
    """
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    bundle_id = _bundle_id(underlying_name, view)
    created_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path) as connection:
        _schema(connection)
        connection.execute(
            """
            INSERT INTO market_evidence_bundles (
                bundle_id, underlying_name, as_of_timestamp,
                underlying_timestamp, futures_market_timestamp,
                futures_collection_timestamp, option_timestamp,
                observed_direction, structural_state, direction_state,
                evidence_readiness, contract_quality, trade_eligibility,
                trade_bias, blocking_reasons_json, caution_reasons_json,
                policy_version, payload_json, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(bundle_id) DO NOTHING
            """,
            (
                bundle_id,
                underlying_name,
                str(view.get("as_of_timestamp") or created_at),
                view.get("underlying_timestamp"),
                view.get("futures_market_timestamp"),
                view.get("futures_collection_timestamp"),
                view.get("option_timestamp"),
                view.get("observed_direction"),
                view.get("structural_state"),
                view.get("direction_state"),
                view.get("evidence_readiness"),
                view.get("contract_quality"),
                view.get("trade_eligibility"),
                view.get("trade_bias"),
                _json(view.get("blocking_reasons") or []),
                _json(view.get("caution_reasons") or []),
                POLICY_VERSION,
                _json(dict(view)),
                created_at,
            ),
        )
    return bundle_id


def read_latest_market_evidence_bundle(
    database_path: str | Path,
    *,
    underlying_name: str,
) -> dict[str, Any] | None:
    path = Path(database_path)
    if not path.exists():
        return None
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        _schema(connection)
        row = connection.execute(
            """
            SELECT * FROM market_evidence_bundles
            WHERE underlying_name=?
            ORDER BY as_of_timestamp DESC, created_at DESC
            LIMIT 1
            """,
            (underlying_name,),
        ).fetchone()
    if row is None:
        return None
    stored = dict(row)
    try:
        payload = json.loads(stored.get("payload_json") or "{}")
    except json.JSONDecodeError:
        payload = {}
    payload["bundle_id"] = stored["bundle_id"]
    payload["policy_version"] = stored["policy_version"]
    payload["persisted_at"] = stored["created_at"]
    return payload


__all__ = [
    "POLICY_VERSION",
    "persist_market_evidence_bundle",
    "read_latest_market_evidence_bundle",
]
