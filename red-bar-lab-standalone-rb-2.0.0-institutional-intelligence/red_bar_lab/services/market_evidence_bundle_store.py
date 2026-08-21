from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

POLICY_VERSION = "market-evidence-v2"


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _bundle_id(underlying_name: str, view: Mapping[str, Any]) -> str:
    anchor = str(
        view.get("latest_complete_evidence_time")
        or view.get("underlying_timestamp")
        or view.get("option_timestamp")
        or "missing"
    )
    raw = f"{underlying_name}|{anchor}|{POLICY_VERSION}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def persist_market_evidence_bundle(
    database_path: str | Path,
    *,
    underlying_name: str,
    view: Mapping[str, Any],
) -> str:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    bundle_id = _bundle_id(underlying_name, view)
    created_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path) as connection:
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
            INSERT OR REPLACE INTO market_evidence_bundles (
                bundle_id, underlying_name, as_of_timestamp,
                underlying_timestamp, futures_market_timestamp,
                futures_collection_timestamp, option_timestamp,
                observed_direction, structural_state, direction_state,
                evidence_readiness, contract_quality, trade_eligibility,
                trade_bias, blocking_reasons_json, caution_reasons_json,
                policy_version, payload_json, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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


__all__ = ["POLICY_VERSION", "persist_market_evidence_bundle"]
