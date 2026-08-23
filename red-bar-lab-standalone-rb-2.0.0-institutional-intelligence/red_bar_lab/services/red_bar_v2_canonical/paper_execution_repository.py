from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3

from red_bar_lab.domain.red_bar_v2 import Direction, EntryType, OptionSide

from .paper_execution_identity import (
    build_execution_event_id,
    canonical_json,
    payload_sha256,
)
from .paper_execution_models import (
    CanonicalPaperContract,
    CanonicalPaperExecutionCommand,
    PaperExecutionEventType,
    PaperExecutionState,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS canonical_red_bar_v2_paper_commands (
    command_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE,
    reservation_id TEXT NOT NULL UNIQUE,
    bundle_id TEXT NOT NULL,
    signal_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    paper_order_id TEXT,
    reason_code TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rbv2_paper_bundle
ON canonical_red_bar_v2_paper_commands(bundle_id,created_at);
CREATE TABLE IF NOT EXISTS canonical_red_bar_v2_paper_execution_events (
    event_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    command_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_timestamp TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    paper_order_id TEXT,
    metadata_json TEXT NOT NULL,
    metadata_sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rbv2_paper_events
ON canonical_red_bar_v2_paper_execution_events(execution_id,event_timestamp,event_id);
"""


class PaperExecutionStorageError(Exception):
    pass


class PaperExecutionCorruptionError(Exception):
    pass


class PaperExecutionConflictError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class VerifiedPaperExecution:
    command: CanonicalPaperExecutionCommand
    state: PaperExecutionState
    reason_code: str
    paper_order_id: str | None
    events: tuple[tuple[PaperExecutionEventType, datetime, str, str | None], ...]


def _aware(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception as exc:
        raise PaperExecutionCorruptionError(f"invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PaperExecutionCorruptionError(f"naive {field}")
    return parsed


def _same(left: datetime, right: datetime) -> bool:
    return left.astimezone(timezone.utc) == right.astimezone(timezone.utc)


def command_payload(command: CanonicalPaperExecutionCommand) -> str:
    data = asdict(command)
    for key in ("trading_date", "signal_timestamp", "reservation_expiry", "created_at"):
        data[key] = data[key].isoformat()
    for key in ("direction", "option_side", "entry_type"):
        data[key] = data[key].value
    contract = data["contract"]
    contract["expiry"] = contract["expiry"].isoformat()
    contract["option_side"] = contract["option_side"].value
    contract["selected_at"] = contract["selected_at"].isoformat()
    contract["quote_timestamp"] = contract["quote_timestamp"].isoformat()
    return canonical_json(data)


def command_from_payload(payload: str) -> CanonicalPaperExecutionCommand:
    try:
        data = json.loads(payload)
        raw = data["contract"]
        contract = CanonicalPaperContract(
            instrument_token=raw["instrument_token"],
            instrument_key=raw["instrument_key"],
            tradingsymbol=raw["tradingsymbol"],
            exchange=raw["exchange"],
            option_side=OptionSide(raw["option_side"]),
            strike=raw["strike"],
            expiry=date.fromisoformat(raw["expiry"]),
            lot_size=raw["lot_size"],
            selected_at=_aware(raw["selected_at"], "contract selected_at"),
            quote_timestamp=_aware(raw["quote_timestamp"], "contract quote_timestamp"),
            last_price=raw["last_price"],
            best_bid=raw.get("best_bid"),
            best_ask=raw.get("best_ask"),
        )
        return CanonicalPaperExecutionCommand(
            command_id=data["command_id"], execution_id=data["execution_id"],
            reservation_id=data["reservation_id"], bundle_id=data["bundle_id"],
            signal_id=data["signal_id"], idempotency_key=data["idempotency_key"],
            strategy_id=data["strategy_id"], strategy_version=data["strategy_version"],
            instrument_key=data["instrument_key"], trading_date=date.fromisoformat(data["trading_date"]),
            direction=Direction(data["direction"]), option_side=OptionSide(data["option_side"]),
            entry_type=EntryType(data["entry_type"]),
            signal_timestamp=_aware(data["signal_timestamp"], "signal_timestamp"),
            reservation_owner=data["reservation_owner"],
            reservation_expiry=_aware(data["reservation_expiry"], "reservation_expiry"),
            contract=contract, quantity=data["quantity"], order_side=data["order_side"],
            order_type=data["order_type"], limit_price=data.get("limit_price"),
            created_at=_aware(data["created_at"], "created_at"),
            schema_version=data["schema_version"],
        )
    except PaperExecutionCorruptionError:
        raise
    except Exception as exc:
        raise PaperExecutionCorruptionError("command payload violates schema") from exc


class SQLiteCanonicalPaperExecutionRepository:
    def __init__(self, path: Path, *, initialize: bool = True) -> None:
        self.path = Path(path)
        if initialize:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.executescript(SCHEMA)

    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        try:
            if read_only:
                if not self.path.exists():
                    raise FileNotFoundError(str(self.path))
                conn = sqlite3.connect(f"file:{self.path.resolve().as_posix()}?mode=ro", uri=True)
            else:
                conn = sqlite3.connect(self.path, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=5000")
            return conn
        except (sqlite3.Error, OSError) as exc:
            raise PaperExecutionStorageError("paper execution database unavailable") from exc

    @staticmethod
    def _insert_event(
        conn: sqlite3.Connection,
        *, command: CanonicalPaperExecutionCommand,
        event_type: PaperExecutionEventType,
        at: datetime,
        reason_code: str,
        paper_order_id: str | None,
    ) -> None:
        event_id = build_execution_event_id(
            execution_id=command.execution_id,
            event_type=event_type.value,
            event_timestamp=at,
            reason_code=reason_code,
        )
        metadata = canonical_json({
            "execution_id": command.execution_id,
            "command_id": command.command_id,
            "state": event_type.value.replace("COMMAND_", "").replace("SUBMISSION_", "SUBMISSION_"),
        })
        existing = conn.execute(
            "SELECT * FROM canonical_red_bar_v2_paper_execution_events WHERE event_id=?",
            (event_id,),
        ).fetchone()
        values = (
            event_id, command.execution_id, command.command_id, event_type.value,
            at.isoformat(), reason_code, paper_order_id, metadata, payload_sha256(metadata),
        )
        if existing is not None:
            actual = tuple(existing[key] for key in (
                "event_id", "execution_id", "command_id", "event_type", "event_timestamp",
                "reason_code", "paper_order_id", "metadata_json", "metadata_sha256",
            ))
            if actual != values:
                raise PaperExecutionConflictError("paper execution event conflict")
            return
        conn.execute(
            "INSERT INTO canonical_red_bar_v2_paper_execution_events VALUES(?,?,?,?,?,?,?,?,?)",
            values,
        )

    def prepare(self, command: CanonicalPaperExecutionCommand) -> VerifiedPaperExecution:
        payload = command_payload(command)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT execution_id FROM canonical_red_bar_v2_paper_commands WHERE idempotency_key=?",
                (command.idempotency_key,),
            ).fetchone()
            if existing is not None:
                conn.execute("COMMIT")
                return self.get_verified(execution_id=str(existing["execution_id"]))
            conn.execute(
                "INSERT INTO canonical_red_bar_v2_paper_commands VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    command.command_id, command.execution_id, command.reservation_id,
                    command.bundle_id, command.signal_id, command.idempotency_key,
                    PaperExecutionState.PREPARED.value, None, "COMMAND_PREPARED",
                    command.created_at.isoformat(), command.created_at.isoformat(),
                    command.schema_version, payload, payload_sha256(payload),
                ),
            )
            self._insert_event(
                conn, command=command, event_type=PaperExecutionEventType.COMMAND_PREPARED,
                at=command.created_at, reason_code="COMMAND_PREPARED", paper_order_id=None,
            )
            conn.execute("COMMIT")
            return self.get_verified(execution_id=command.execution_id)
        except sqlite3.IntegrityError as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise PaperExecutionConflictError("duplicate canonical paper execution") from exc
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def transition(
        self,
        *,
        execution_id: str,
        expected_state: PaperExecutionState,
        new_state: PaperExecutionState,
        event_type: PaperExecutionEventType,
        at: datetime,
        reason_code: str,
        paper_order_id: str | None = None,
    ) -> VerifiedPaperExecution:
        current = self.get_verified(execution_id=execution_id)
        allowed = {
            PaperExecutionState.PREPARED: {PaperExecutionState.SUBMISSION_STARTED, PaperExecutionState.RECOVERY_REQUIRED},
            PaperExecutionState.SUBMISSION_STARTED: {PaperExecutionState.PAPER_ACCEPTED, PaperExecutionState.PAPER_REJECTED, PaperExecutionState.SUBMISSION_UNCERTAIN},
            PaperExecutionState.PAPER_ACCEPTED: {PaperExecutionState.PAPER_FILLED, PaperExecutionState.RECOVERY_REQUIRED},
            PaperExecutionState.SUBMISSION_UNCERTAIN: {PaperExecutionState.PAPER_ACCEPTED, PaperExecutionState.PAPER_REJECTED, PaperExecutionState.RECOVERY_REQUIRED},
            PaperExecutionState.RECOVERY_REQUIRED: {PaperExecutionState.PAPER_ACCEPTED, PaperExecutionState.PAPER_REJECTED, PaperExecutionState.SUBMISSION_UNCERTAIN},
        }
        if current.state is not expected_state or new_state not in allowed.get(current.state, set()):
            raise PaperExecutionConflictError("invalid paper execution transition")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "UPDATE canonical_red_bar_v2_paper_commands SET state=?,paper_order_id=?,reason_code=?,updated_at=? WHERE execution_id=? AND state=?",
                (new_state.value, paper_order_id, reason_code, at.isoformat(), execution_id, expected_state.value),
            )
            if cursor.rowcount != 1:
                raise PaperExecutionConflictError("paper execution transition conflict")
            self._insert_event(
                conn, command=current.command, event_type=event_type, at=at,
                reason_code=reason_code, paper_order_id=paper_order_id,
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        return self.get_verified(execution_id=execution_id)

    def get_verified(self, *, execution_id: str) -> VerifiedPaperExecution:
        with self._connect(read_only=True) as conn:
            row = conn.execute(
                "SELECT * FROM canonical_red_bar_v2_paper_commands WHERE execution_id=?",
                (execution_id,),
            ).fetchone()
            if row is None:
                raise LookupError("canonical paper execution not found")
            payload = str(row["payload_json"])
            if payload_sha256(payload) != str(row["payload_sha256"]):
                raise PaperExecutionCorruptionError("command digest mismatch")
            command = command_from_payload(payload)
            projections = {
                "command_id": command.command_id, "execution_id": command.execution_id,
                "reservation_id": command.reservation_id, "bundle_id": command.bundle_id,
                "signal_id": command.signal_id, "idempotency_key": command.idempotency_key,
                "schema_version": command.schema_version,
            }
            for field, expected in projections.items():
                if row[field] != expected:
                    raise PaperExecutionCorruptionError(f"command projection mismatch: {field}")
            state = PaperExecutionState(str(row["state"]))
            event_rows = conn.execute(
                "SELECT * FROM canonical_red_bar_v2_paper_execution_events WHERE execution_id=? ORDER BY event_timestamp,event_id",
                (execution_id,),
            ).fetchall()
        if not event_rows:
            raise PaperExecutionCorruptionError("paper execution has no lifecycle history")
        events = []
        for item in event_rows:
            metadata = str(item["metadata_json"])
            if payload_sha256(metadata) != str(item["metadata_sha256"]):
                raise PaperExecutionCorruptionError("paper execution event digest mismatch")
            expected_id = build_execution_event_id(
                execution_id=command.execution_id, event_type=str(item["event_type"]),
                event_timestamp=_aware(item["event_timestamp"], "event_timestamp"),
                reason_code=str(item["reason_code"]),
            )
            if item["event_id"] != expected_id or item["command_id"] != command.command_id:
                raise PaperExecutionCorruptionError("paper execution event identity mismatch")
            events.append((PaperExecutionEventType(str(item["event_type"])), _aware(item["event_timestamp"], "event_timestamp"), str(item["reason_code"]), item["paper_order_id"]))
        if events[0][0] is not PaperExecutionEventType.COMMAND_PREPARED:
            raise PaperExecutionCorruptionError("prepared event must be first")
        expected_last = {
            PaperExecutionState.PREPARED: PaperExecutionEventType.COMMAND_PREPARED,
            PaperExecutionState.SUBMISSION_STARTED: PaperExecutionEventType.SUBMISSION_STARTED,
            PaperExecutionState.PAPER_ACCEPTED: PaperExecutionEventType.PAPER_ACCEPTED,
            PaperExecutionState.PAPER_FILLED: PaperExecutionEventType.PAPER_FILLED,
            PaperExecutionState.PAPER_REJECTED: PaperExecutionEventType.PAPER_REJECTED,
            PaperExecutionState.SUBMISSION_UNCERTAIN: PaperExecutionEventType.SUBMISSION_UNCERTAIN,
            PaperExecutionState.RECOVERY_REQUIRED: PaperExecutionEventType.RECOVERY_REQUIRED,
        }[state]
        if events[-1][0] is not expected_last:
            raise PaperExecutionCorruptionError("paper execution state/history mismatch")
        terminal = {PaperExecutionState.PAPER_FILLED, PaperExecutionState.PAPER_REJECTED}
        if state in terminal and any(event[1] > events[-1][1] for event in events):
            raise PaperExecutionCorruptionError("event after terminal state")
        return VerifiedPaperExecution(
            command=command, state=state, reason_code=str(row["reason_code"]),
            paper_order_id=row["paper_order_id"], events=tuple(events),
        )

    def list_non_terminal(self, *, limit: int = 100) -> tuple[str, ...]:
        bounded = min(max(int(limit), 1), 500)
        with self._connect(read_only=True) as conn:
            rows = conn.execute(
                "SELECT execution_id FROM canonical_red_bar_v2_paper_commands WHERE state NOT IN ('PAPER_FILLED','PAPER_REJECTED') ORDER BY updated_at LIMIT ?",
                (bounded,),
            ).fetchall()
        return tuple(str(row["execution_id"]) for row in rows)
