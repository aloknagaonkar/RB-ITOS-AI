from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sqlite3

from red_bar_lab.domain.red_bar_v2 import RedBarV2SignalBundle, red_bar_v2_bundle_from_dict

from .persistence_identity import payload_sha256
from .persistence_models import (
    CanonicalBundleEventType,
    CanonicalBundleLifecycleEvent,
    CanonicalPersistenceCorruptionError,
    PersistedRedBarV2Resolution,
)
from .persistence_serialization import lifecycle_event_from_json, resolution_envelope_from_json


@dataclass(frozen=True, slots=True)
class VerifiedCanonicalBundleEvidence:
    resolution: PersistedRedBarV2Resolution
    bundle: RedBarV2SignalBundle
    events: tuple[CanonicalBundleLifecycleEvent, ...]


def _aware_iso(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception as exc:
        raise CanonicalPersistenceCorruptionError(f"invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CanonicalPersistenceCorruptionError(f"naive {field}")
    return parsed


def _same_instant(left: datetime, right: datetime) -> bool:
    return (
        left.tzinfo is not None
        and left.utcoffset() is not None
        and right.tzinfo is not None
        and right.utcoffset() is not None
        and left.astimezone(timezone.utc) == right.astimezone(timezone.utc)
    )


def _decode_resolution(row: sqlite3.Row) -> PersistedRedBarV2Resolution:
    payload = str(row["payload_json"])
    if payload_sha256(payload) != str(row["payload_sha256"]):
        raise CanonicalPersistenceCorruptionError("resolution payload digest mismatch")
    try:
        resolution = resolution_envelope_from_json(payload)
    except Exception as exc:
        raise CanonicalPersistenceCorruptionError("resolution payload violates canonical schema") from exc
    projections: dict[str, object] = {
        "resolution_id": resolution.resolution_id,
        "instrument_key": resolution.instrument_key,
        "trading_date": resolution.trading_date.isoformat(),
        "source_replay_id": resolution.source_replay_id,
        "resolution_schema_version": resolution.schema_version,
        "bundle_id": resolution.section_3.bundle_id if resolution.section_3 else None,
    }
    for field, expected in projections.items():
        if row[field] != expected:
            raise CanonicalPersistenceCorruptionError(f"resolution projection mismatch: {field}")
    _aware_iso(row["persisted_at"], "persisted_at")
    if resolution.section_3 is None:
        raise CanonicalPersistenceCorruptionError("resolution references no canonical bundle")
    return resolution


def _decode_bundle(row: sqlite3.Row) -> RedBarV2SignalBundle:
    payload = str(row["payload_json"])
    if payload_sha256(payload) != str(row["payload_sha256"]):
        raise CanonicalPersistenceCorruptionError("bundle payload digest mismatch")
    try:
        bundle = red_bar_v2_bundle_from_dict(json.loads(payload))
    except Exception as exc:
        raise CanonicalPersistenceCorruptionError("bundle payload violates canonical schema") from exc
    projections: dict[str, object] = {
        "bundle_id": bundle.bundle_id,
        "signal_id": bundle.signal_id,
        "idempotency_key": bundle.idempotency_key,
        "strategy_id": bundle.strategy_id,
        "strategy_version": bundle.strategy_version,
        "instrument_key": bundle.instrument_key,
        "trading_date": bundle.trading_date.isoformat(),
        "entry_type": bundle.entry_type.value,
        "direction": bundle.direction.value,
        "option_side": bundle.option_side.value,
        "bundle_schema_version": bundle.schema_version,
    }
    for field, expected in projections.items():
        if row[field] != expected:
            raise CanonicalPersistenceCorruptionError(f"bundle projection mismatch: {field}")
    stored = _aware_iso(row["evaluation_timestamp"], "bundle evaluation_timestamp")
    if not _same_instant(stored, bundle.evaluation_timestamp):
        raise CanonicalPersistenceCorruptionError("bundle projection mismatch: evaluation_timestamp")
    return bundle


def _decode_event(row: sqlite3.Row, bundle_id: str) -> CanonicalBundleLifecycleEvent:
    payload = str(row["metadata_json"])
    if payload_sha256(payload) != str(row["metadata_sha256"]):
        raise CanonicalPersistenceCorruptionError("lifecycle event digest mismatch")
    try:
        event = lifecycle_event_from_json(payload)
    except Exception as exc:
        raise CanonicalPersistenceCorruptionError("lifecycle event payload violates canonical schema") from exc
    if event.bundle_id != bundle_id:
        raise CanonicalPersistenceCorruptionError("lifecycle event projection mismatch: requested_bundle_id")
    projections: dict[str, object] = {
        "event_id": event.event_id,
        "bundle_id": event.bundle_id,
        "event_type": event.event_type.value,
        "source": event.source,
        "reason_code": event.reason_code,
    }
    for field, expected in projections.items():
        if row[field] != expected:
            raise CanonicalPersistenceCorruptionError(f"lifecycle event projection mismatch: {field}")
    stored = _aware_iso(row["event_timestamp"], "lifecycle event_timestamp")
    if not _same_instant(stored, event.event_timestamp):
        raise CanonicalPersistenceCorruptionError("lifecycle event projection mismatch: event_timestamp")
    return event


def verify_canonical_bundle_evidence(
    conn: sqlite3.Connection,
    *,
    bundle_id: str,
) -> VerifiedCanonicalBundleEvidence:
    try:
        resolution_rows = conn.execute(
            "SELECT * FROM canonical_red_bar_v2_resolutions WHERE bundle_id=? ORDER BY evaluation_timestamp DESC,resolution_id DESC",
            (bundle_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        if "no such table" in str(exc).lower():
            raise CanonicalPersistenceCorruptionError("resolution references missing resolution table") from exc
        raise
    if not resolution_rows:
        raise CanonicalPersistenceCorruptionError("BUNDLE_ORPHANED")
    resolutions = tuple(_decode_resolution(row) for row in resolution_rows)
    resolution = resolutions[0]
    if any(item.section_3 != resolution.section_3 for item in resolutions[1:]):
        raise CanonicalPersistenceCorruptionError("multiple conflicting resolutions reference bundle")
    if resolution.section_3 is None or resolution.section_3.bundle_id != bundle_id:
        raise CanonicalPersistenceCorruptionError("resolution bundle reference mismatch")

    try:
        bundle_row = conn.execute(
            "SELECT bundle_id,signal_id,idempotency_key,strategy_id,strategy_version,instrument_key,trading_date,evaluation_timestamp,entry_type,direction,option_side,bundle_schema_version,payload_json,payload_sha256 FROM canonical_red_bar_v2_bundles WHERE bundle_id=?",
            (bundle_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        if "no such table" in str(exc).lower():
            raise CanonicalPersistenceCorruptionError("resolution references missing bundle table") from exc
        raise
    if bundle_row is None:
        raise CanonicalPersistenceCorruptionError("resolution references missing bundle")
    bundle = _decode_bundle(bundle_row)
    if bundle != resolution.section_3:
        raise CanonicalPersistenceCorruptionError("resolution embedded bundle does not match stored bundle")

    try:
        event_rows = conn.execute(
            "SELECT event_id,bundle_id,event_type,event_timestamp,source,reason_code,metadata_json,metadata_sha256 FROM canonical_red_bar_v2_bundle_events WHERE bundle_id=? ORDER BY event_timestamp ASC,event_id ASC",
            (bundle_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        if "no such table" in str(exc).lower():
            raise CanonicalPersistenceCorruptionError("bundle references missing lifecycle event table") from exc
        raise
    if not event_rows:
        raise CanonicalPersistenceCorruptionError("bundle has no lifecycle event history")
    events = tuple(_decode_event(row, bundle_id) for row in event_rows)
    if not any(event.event_type is CanonicalBundleEventType.BUNDLE_AVAILABLE for event in events):
        raise CanonicalPersistenceCorruptionError("bundle has no BUNDLE_AVAILABLE lifecycle event")
    return VerifiedCanonicalBundleEvidence(resolution=resolution, bundle=bundle, events=events)
