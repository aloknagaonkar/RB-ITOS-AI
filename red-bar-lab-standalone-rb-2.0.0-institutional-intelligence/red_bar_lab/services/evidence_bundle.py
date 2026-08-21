from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


EVIDENCE_BUNDLE_POLICY_VERSION = "operations-evidence-bundle-v1"


@dataclass(frozen=True)
class EvidenceBundle:
    bundle_id: str
    signal_id: str
    strategy_id: str
    as_of_timestamp: str | None
    operations_policy_version: str
    authority: str
    reference: dict[str, Any]
    market: dict[str, Any]
    volume: dict[str, Any]
    options: dict[str, Any]
    core_eligible: bool
    hybrid_eligible: bool
    blocking_reasons: tuple[str, ...]
    advisory_reasons: tuple[str, ...]
    bundle_policy_version: str = EVIDENCE_BUNDLE_POLICY_VERSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _bundle_id(
    *,
    signal_id: str,
    as_of_timestamp: object,
    operations_policy_version: str,
) -> str:
    material = "|".join(
        (
            signal_id,
            str(as_of_timestamp or ""),
            operations_policy_version,
            EVIDENCE_BUNDLE_POLICY_VERSION,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _stage_payload(row: Mapping[str, Any], prefix: str, status_key: str) -> dict[str, Any]:
    return {
        "status": row.get(status_key),
        "source": row.get(f"{prefix}_source"),
        "input_cutoff_timestamp": row.get(f"{prefix}_cutoff_timestamp"),
        "latest_source_timestamp": row.get(f"{prefix}_latest_timestamp"),
        "row_count": int(row.get(f"{prefix}_row_count") or 0),
        "fallback_used": bool(row.get(f"{prefix}_fallback_used")),
        "no_lookahead_passed": row.get(f"{prefix}_no_lookahead_passed"),
        "mandatory_present": int(row.get(f"{prefix}_mandatory_present") or 0),
        "mandatory_expected": int(row.get(f"{prefix}_mandatory_expected") or 0),
        "mandatory_coverage_pct": float(row.get(f"{prefix}_mandatory_coverage_pct") or 0.0),
        "optional_present": int(row.get(f"{prefix}_optional_present") or 0),
        "optional_expected": int(row.get(f"{prefix}_optional_expected") or 0),
        "optional_coverage_pct": float(row.get(f"{prefix}_optional_coverage_pct") or 0.0),
        "missing_mandatory_fields": tuple(row.get(f"{prefix}_missing_mandatory_fields") or ()),
        "missing_optional_fields": tuple(row.get(f"{prefix}_missing_optional_fields") or ()),
    }


def build_evidence_bundles(
    readiness_gate: Mapping[str, Any],
    *,
    strategy_id: str = "RED_BAR_V2",
) -> tuple[EvidenceBundle, ...]:
    policy = str(readiness_gate.get("policy_version") or "UNKNOWN")
    authority = str(readiness_gate.get("authority") or "OBSERVATIONAL_ONLY")
    references = readiness_gate.get("reference_results") or {}
    bundles: list[EvidenceBundle] = []

    for original in readiness_gate.get("drilldown") or ():
        row = dict(original)
        signal_id = str(row.get("signal_id") or "").strip()
        if not signal_id:
            continue
        as_of = row.get("confirmation_timestamp")
        reasons = tuple(str(value) for value in row.get("all_reasons") or () if str(value))
        reference = dict(references.get(signal_id) or {})
        reference.update(
            {
                "status": row.get("reference_status"),
                "reference_type": row.get("reference_type"),
                "reference_timestamp": row.get("reference_timestamp"),
            }
        )
        option_payload = {
            "status": row.get("option_status"),
            "mandatory_present": int(row.get("option_mandatory_present") or 0),
            "mandatory_expected": int(row.get("option_mandatory_expected") or 0),
            "mandatory_coverage_pct": float(row.get("option_mandatory_coverage_pct") or 0.0),
            "optional_present": int(row.get("option_optional_present") or 0),
            "optional_expected": int(row.get("option_optional_expected") or 0),
            "optional_coverage_pct": float(row.get("option_optional_coverage_pct") or 0.0),
            "missing_mandatory_fields": tuple(row.get("option_missing_mandatory_fields") or ()),
            "missing_optional_fields": tuple(row.get("option_missing_optional_fields") or ()),
        }
        bundles.append(
            EvidenceBundle(
                bundle_id=_bundle_id(
                    signal_id=signal_id,
                    as_of_timestamp=as_of,
                    operations_policy_version=policy,
                ),
                signal_id=signal_id,
                strategy_id=strategy_id,
                as_of_timestamp=str(as_of) if as_of is not None else None,
                operations_policy_version=policy,
                authority=authority,
                reference=reference,
                market=_stage_payload(row, "market", "market_status"),
                volume=_stage_payload(row, "volume", "volume_status"),
                options=option_payload,
                core_eligible=bool(row.get("core_eligible")),
                hybrid_eligible=bool(row.get("hybrid_eligible")),
                blocking_reasons=reasons,
                advisory_reasons=(),
            )
        )
    return tuple(bundles)


def ensure_evidence_bundle_schema(database_path: str | Path) -> None:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS operations_evidence_bundles (
                bundle_id TEXT PRIMARY KEY,
                signal_id TEXT NOT NULL,
                strategy_id TEXT NOT NULL,
                as_of_timestamp TEXT,
                operations_policy_version TEXT NOT NULL,
                authority TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_operations_evidence_signal "
            "ON operations_evidence_bundles(signal_id, as_of_timestamp)"
        )


def persist_evidence_bundles(
    database_path: str | Path,
    bundles: Iterable[EvidenceBundle | Mapping[str, Any]],
) -> tuple[str, ...]:
    ensure_evidence_bundle_schema(database_path)
    ids: list[str] = []
    with sqlite3.connect(Path(database_path)) as connection:
        for bundle in bundles:
            payload = bundle.as_dict() if isinstance(bundle, EvidenceBundle) else dict(bundle)
            bundle_id = str(payload["bundle_id"])
            connection.execute(
                """
                INSERT INTO operations_evidence_bundles (
                    bundle_id, signal_id, strategy_id, as_of_timestamp,
                    operations_policy_version, authority, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(bundle_id) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    authority=excluded.authority,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    bundle_id,
                    payload.get("signal_id"),
                    payload.get("strategy_id"),
                    payload.get("as_of_timestamp"),
                    payload.get("operations_policy_version"),
                    payload.get("authority") or "OBSERVATIONAL_ONLY",
                    json.dumps(payload, sort_keys=True, default=str),
                ),
            )
            ids.append(bundle_id)
    return tuple(ids)


def read_evidence_bundles(database_path: str | Path) -> tuple[dict[str, Any], ...]:
    path = Path(database_path)
    if not path.exists():
        return ()
    ensure_evidence_bundle_schema(path)
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT payload_json FROM operations_evidence_bundles "
            "ORDER BY as_of_timestamp, signal_id"
        ).fetchall()
    return tuple(json.loads(row[0]) for row in rows)


def evidence_bundles_json(bundles: Iterable[EvidenceBundle | Mapping[str, Any]]) -> str:
    payload = [bundle.as_dict() if isinstance(bundle, EvidenceBundle) else dict(bundle) for bundle in bundles]
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


def evidence_bundles_csv(bundles: Iterable[EvidenceBundle | Mapping[str, Any]]) -> str:
    rows = []
    for bundle in bundles:
        payload = bundle.as_dict() if isinstance(bundle, EvidenceBundle) else dict(bundle)
        rows.append(
            {
                "bundle_id": payload.get("bundle_id"),
                "signal_id": payload.get("signal_id"),
                "as_of_timestamp": payload.get("as_of_timestamp"),
                "reference_status": (payload.get("reference") or {}).get("status"),
                "market_status": (payload.get("market") or {}).get("status"),
                "volume_status": (payload.get("volume") or {}).get("status"),
                "option_status": (payload.get("options") or {}).get("status"),
                "core_eligible": payload.get("core_eligible"),
                "hybrid_eligible": payload.get("hybrid_eligible"),
                "blocking_reasons": "|".join(payload.get("blocking_reasons") or ()),
                "authority": payload.get("authority"),
            }
        )
    output = io.StringIO()
    fields = tuple(rows[0].keys()) if rows else (
        "bundle_id", "signal_id", "as_of_timestamp", "reference_status",
        "market_status", "volume_status", "option_status", "core_eligible",
        "hybrid_eligible", "blocking_reasons", "authority",
    )
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


__all__ = [
    "EVIDENCE_BUNDLE_POLICY_VERSION",
    "EvidenceBundle",
    "build_evidence_bundles",
    "ensure_evidence_bundle_schema",
    "persist_evidence_bundles",
    "read_evidence_bundles",
    "evidence_bundles_json",
    "evidence_bundles_csv",
]
