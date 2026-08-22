from __future__ import annotations

from datetime import date, datetime
import hmac
import json
from pathlib import Path
import sqlite3
from time import perf_counter_ns

from red_bar_lab.domain.red_bar_v2 import (
    RedBarV2SignalBundle,
    red_bar_v2_bundle_from_dict,
    red_bar_v2_bundle_to_dict,
)

from .persistence_identity import build_canonical_bundle_event_id, canonical_json, payload_sha256
from .persistence_models import (
    CanonicalBundleEventType,
    CanonicalBundleLifecycleEvent,
    CanonicalPersistenceConflictError,
    CanonicalPersistenceCorruptionError,
    CanonicalPersistenceResult,
    CanonicalPersistenceUnavailableError,
    PersistenceOutcome,
    PersistedRedBarV2Resolution,
)
from .persistence_serialization import (
    lifecycle_event_from_json,
    lifecycle_event_to_json,
    resolution_envelope_from_json,
    resolution_envelope_to_json,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS canonical_red_bar_v2_resolutions (
    resolution_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    instrument_key TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    evaluation_timestamp TEXT NOT NULL,
    source_replay_id TEXT NOT NULL,
    admission_outcome TEXT NOT NULL,
    direction TEXT,
    option_side TEXT,
    entry_type TEXT,
    bundle_id TEXT,
    resolution_schema_version TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    persisted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_canonical_rbv2_resolution_session
ON canonical_red_bar_v2_resolutions(instrument_key, trading_date, evaluation_timestamp);
CREATE INDEX IF NOT EXISTS idx_canonical_rbv2_resolution_replay
ON canonical_red_bar_v2_resolutions(source_replay_id);

CREATE TABLE IF NOT EXISTS canonical_red_bar_v2_bundles (
    bundle_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL UNIQUE,
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    instrument_key TEXT NOT NULL,
    trading_date TEXT NOT NULL,
    evaluation_timestamp TEXT NOT NULL,
    entry_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    option_side TEXT NOT NULL,
    bundle_schema_version TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    first_persisted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_canonical_rbv2_bundle_session
ON canonical_red_bar_v2_bundles(instrument_key, trading_date, evaluation_timestamp);

CREATE TABLE IF NOT EXISTS canonical_red_bar_v2_bundle_events (
    event_id TEXT PRIMARY KEY,
    bundle_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_timestamp TEXT NOT NULL,
    source TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    metadata_sha256 TEXT NOT NULL,
    FOREIGN KEY(bundle_id) REFERENCES canonical_red_bar_v2_bundles(bundle_id)
);
CREATE INDEX IF NOT EXISTS idx_canonical_rbv2_bundle_event_history
ON canonical_red_bar_v2_bundle_events(bundle_id, event_timestamp);
"""


class SQLiteRedBarV2CanonicalRepository:
    def __init__(self, path: Path, *, busy_timeout_ms: int = 5000) -> None:
        self.path = Path(path)
        self.busy_timeout_ms = int(busy_timeout_ms)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.path,
            timeout=max(self.busy_timeout_ms / 1000.0, 0.1),
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        return conn

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._connect() as conn:
                conn.executescript(SCHEMA)
        except sqlite3.Error as exc:
            raise CanonicalPersistenceUnavailableError(
                f"unable to initialize canonical persistence: {exc}"
            ) from exc

    @staticmethod
    def _verify(payload_json: str, digest: str, label: str) -> None:
        if not hmac.compare_digest(payload_sha256(payload_json), digest):
            raise CanonicalPersistenceCorruptionError(f"{label} payload digest mismatch")

    @classmethod
    def _same_or_conflict(
        cls,
        row: sqlite3.Row | None,
        *,
        digest: str,
        label: str,
    ) -> bool:
        if row is None:
            return False
        stored_json = str(row["payload_json"])
        stored_digest = str(row["payload_sha256"])
        cls._verify(stored_json, stored_digest, label)
        if not hmac.compare_digest(stored_digest, digest):
            raise CanonicalPersistenceConflictError(f"conflicting immutable {label} payload")
        return True

    @staticmethod
    def _available_event(bundle: RedBarV2SignalBundle) -> CanonicalBundleLifecycleEvent:
        event_type = CanonicalBundleEventType.BUNDLE_AVAILABLE
        source = "CANONICAL_RESOLVER"
        reason_code = "CANONICAL_ADMISSION_ALLOWED"
        timestamp = bundle.created_at
        return CanonicalBundleLifecycleEvent(
            event_id=build_canonical_bundle_event_id(
                bundle_id=bundle.bundle_id,
                event_type=event_type.value,
                event_timestamp=timestamp,
                source=source,
                reason_code=reason_code,
            ),
            bundle_id=bundle.bundle_id,
            event_type=event_type,
            event_timestamp=timestamp,
            source=source,
            reason_code=reason_code,
            metadata={
                "signal_id": bundle.signal_id,
                "idempotency_key": bundle.idempotency_key,
            },
        )

    def persist_resolution(self, envelope: PersistedRedBarV2Resolution) -> CanonicalPersistenceResult:
        started = perf_counter_ns()
        persisted_at = datetime.now().astimezone()
        resolution_json = resolution_envelope_to_json(envelope)
        resolution_digest = payload_sha256(resolution_json)
        bundle = envelope.section_3
        bundle_json = canonical_json(red_bar_v2_bundle_to_dict(bundle)) if bundle else None
        bundle_digest = payload_sha256(bundle_json) if bundle_json else None
        event = self._available_event(bundle) if bundle else None
        event_json = lifecycle_event_to_json(event) if event else None
        event_digest = payload_sha256(event_json) if event_json else None
        payload_size = len(resolution_json.encode("utf-8")) + (
            len(bundle_json.encode("utf-8")) if bundle_json else 0
        )
        resolution_inserted = bundle_inserted = lifecycle_inserted = False

        try:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                resolution_row = conn.execute(
                    "SELECT payload_json,payload_sha256 FROM canonical_red_bar_v2_resolutions WHERE resolution_id=?",
                    (envelope.resolution_id,),
                ).fetchone()
                resolution_exists = self._same_or_conflict(
                    resolution_row,
                    digest=resolution_digest,
                    label="resolution",
                )

                bundle_exists = False
                if bundle is not None and bundle_json is not None and bundle_digest is not None:
                    bundle_row = conn.execute(
                        """
                        SELECT bundle_id,signal_id,idempotency_key,
                               payload_json,payload_sha256
                        FROM canonical_red_bar_v2_bundles
                        WHERE bundle_id=? OR signal_id=? OR idempotency_key=?
                        """,
                        (bundle.bundle_id, bundle.signal_id, bundle.idempotency_key),
                    ).fetchone()
                    if bundle_row is not None and (
                        bundle_row["bundle_id"] != bundle.bundle_id
                        or bundle_row["signal_id"] != bundle.signal_id
                        or bundle_row["idempotency_key"] != bundle.idempotency_key
                    ):
                        raise CanonicalPersistenceConflictError("bundle identity unique-key collision")
                    bundle_exists = self._same_or_conflict(
                        bundle_row,
                        digest=bundle_digest,
                        label="bundle",
                    )

                event_exists = False
                if event is not None and event_json is not None and event_digest is not None:
                    event_row = conn.execute(
                        """
                        SELECT metadata_json AS payload_json,
                               metadata_sha256 AS payload_sha256
                        FROM canonical_red_bar_v2_bundle_events
                        WHERE event_id=?
                        """,
                        (event.event_id,),
                    ).fetchone()
                    event_exists = self._same_or_conflict(
                        event_row,
                        digest=event_digest,
                        label="lifecycle event",
                    )

                if not bundle_exists and bundle is not None and bundle_json is not None and bundle_digest is not None:
                    conn.execute(
                        """
                        INSERT INTO canonical_red_bar_v2_bundles(
                            bundle_id,signal_id,idempotency_key,strategy_id,
                            strategy_version,instrument_key,trading_date,
                            evaluation_timestamp,entry_type,direction,option_side,
                            bundle_schema_version,payload_json,payload_sha256,
                            first_persisted_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            bundle.bundle_id,
                            bundle.signal_id,
                            bundle.idempotency_key,
                            bundle.strategy_id,
                            bundle.strategy_version,
                            bundle.instrument_key,
                            bundle.trading_date.isoformat(),
                            bundle.evaluation_timestamp.isoformat(),
                            bundle.entry_type.value,
                            bundle.direction.value,
                            bundle.option_side.value,
                            bundle.schema_version,
                            bundle_json,
                            bundle_digest,
                            persisted_at.isoformat(),
                        ),
                    )
                    bundle_inserted = True

                if not event_exists and event is not None and event_json is not None and event_digest is not None:
                    conn.execute(
                        """
                        INSERT INTO canonical_red_bar_v2_bundle_events(
                            event_id,bundle_id,event_type,event_timestamp,
                            source,reason_code,metadata_json,metadata_sha256
                        ) VALUES(?,?,?,?,?,?,?,?)
                        """,
                        (
                            event.event_id,
                            event.bundle_id,
                            event.event_type.value,
                            event.event_timestamp.isoformat(),
                            event.source,
                            event.reason_code,
                            event_json,
                            event_digest,
                        ),
                    )
                    lifecycle_inserted = True

                if not resolution_exists:
                    decision = envelope.section_2
                    conn.execute(
                        """
                        INSERT INTO canonical_red_bar_v2_resolutions(
                            resolution_id,strategy_id,strategy_version,
                            instrument_key,trading_date,evaluation_timestamp,
                            source_replay_id,admission_outcome,direction,
                            option_side,entry_type,bundle_id,
                            resolution_schema_version,payload_json,
                            payload_sha256,persisted_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            envelope.resolution_id,
                            decision.strategy_id,
                            decision.strategy_version,
                            envelope.instrument_key,
                            envelope.trading_date.isoformat(),
                            decision.evaluation_timestamp.isoformat(),
                            envelope.source_replay_id,
                            decision.admission_outcome.value,
                            decision.direction.value if decision.direction else None,
                            decision.option_side.value if decision.option_side else None,
                            decision.entry_type.value if decision.entry_type else None,
                            bundle.bundle_id if bundle else None,
                            envelope.schema_version,
                            resolution_json,
                            resolution_digest,
                            persisted_at.isoformat(),
                        ),
                    )
                    resolution_inserted = True

                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()
        except (CanonicalPersistenceConflictError, CanonicalPersistenceCorruptionError):
            raise
        except sqlite3.Error as exc:
            raise CanonicalPersistenceUnavailableError(
                f"canonical persistence transaction failed: {exc}"
            ) from exc

        inserted = resolution_inserted or bundle_inserted or lifecycle_inserted
        return CanonicalPersistenceResult(
            resolution_id=envelope.resolution_id,
            bundle_id=bundle.bundle_id if bundle else None,
            outcome=PersistenceOutcome.INSERTED if inserted else PersistenceOutcome.IDEMPOTENT_REPLAY,
            resolution_inserted=resolution_inserted,
            bundle_inserted=bundle_inserted,
            lifecycle_event_inserted=lifecycle_inserted,
            conflict_detected=False,
            persisted_at=persisted_at,
            duration_ms=(perf_counter_ns() - started) / 1_000_000.0,
            payload_size_bytes=payload_size,
        )

    def _resolution(self, row: sqlite3.Row) -> PersistedRedBarV2Resolution:
        payload_json = str(row["payload_json"])
        self._verify(payload_json, str(row["payload_sha256"]), "resolution")
        envelope = resolution_envelope_from_json(payload_json)
        projections = {
            "resolution_id": envelope.resolution_id,
            "instrument_key": envelope.instrument_key,
            "trading_date": envelope.trading_date.isoformat(),
            "source_replay_id": envelope.source_replay_id,
            "resolution_schema_version": envelope.schema_version,
            "bundle_id": envelope.section_3.bundle_id if envelope.section_3 else None,
        }
        for name, expected in projections.items():
            if row[name] != expected:
                raise CanonicalPersistenceCorruptionError(
                    f"resolution projection mismatch: {name}"
                )
        return envelope

    def get_resolution(self, resolution_id: str) -> PersistedRedBarV2Resolution | None:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM canonical_red_bar_v2_resolutions WHERE resolution_id=?",
                    (resolution_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise CanonicalPersistenceUnavailableError(str(exc)) from exc
        return None if row is None else self._resolution(row)

    def _bundle(self, row: sqlite3.Row) -> RedBarV2SignalBundle:
        payload_json = str(row["payload_json"])
        self._verify(payload_json, str(row["payload_sha256"]), "bundle")
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            raise CanonicalPersistenceCorruptionError("bundle payload is not valid JSON") from exc
        bundle = red_bar_v2_bundle_from_dict(payload)
        projections = {
            "bundle_id": bundle.bundle_id,
            "signal_id": bundle.signal_id,
            "idempotency_key": bundle.idempotency_key,
            "instrument_key": bundle.instrument_key,
            "bundle_schema_version": bundle.schema_version,
        }
        for name, expected in projections.items():
            if row[name] != expected:
                raise CanonicalPersistenceCorruptionError(
                    f"bundle projection mismatch: {name}"
                )
        return bundle

    def get_bundle(self, bundle_id: str) -> RedBarV2SignalBundle | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM canonical_red_bar_v2_bundles WHERE bundle_id=?",
                (bundle_id,),
            ).fetchone()
        return None if row is None else self._bundle(row)

    def get_bundle_by_signal_id(self, signal_id: str) -> RedBarV2SignalBundle | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM canonical_red_bar_v2_bundles WHERE signal_id=?",
                (signal_id,),
            ).fetchone()
        return None if row is None else self._bundle(row)

    def list_session_resolutions(
        self,
        *,
        instrument_key: str,
        trading_date: date,
    ) -> tuple[PersistedRedBarV2Resolution, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM canonical_red_bar_v2_resolutions
                WHERE instrument_key=? AND trading_date=?
                ORDER BY evaluation_timestamp ASC,resolution_id ASC
                """,
                (instrument_key, trading_date.isoformat()),
            ).fetchall()
        return tuple(self._resolution(row) for row in rows)

    def list_bundle_events(self, bundle_id: str) -> tuple[CanonicalBundleLifecycleEvent, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM canonical_red_bar_v2_bundle_events
                WHERE bundle_id=?
                ORDER BY event_timestamp ASC,event_id ASC
                """,
                (bundle_id,),
            ).fetchall()
        events: list[CanonicalBundleLifecycleEvent] = []
        for row in rows:
            payload_json = str(row["metadata_json"])
            self._verify(
                payload_json,
                str(row["metadata_sha256"]),
                "lifecycle event",
            )
            event = lifecycle_event_from_json(payload_json)
            if (
                event.event_id != row["event_id"]
                or event.bundle_id != row["bundle_id"]
                or event.event_type.value != row["event_type"]
                or event.source != row["source"]
                or event.reason_code != row["reason_code"]
            ):
                raise CanonicalPersistenceCorruptionError(
                    "lifecycle event projection mismatch"
                )
            events.append(event)
        return tuple(events)
