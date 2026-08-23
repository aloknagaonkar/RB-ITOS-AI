from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3
from typing import Protocol

from .canonical_evidence_verification import verify_canonical_bundle_evidence
from .persistence_models import CanonicalPersistenceCorruptionError


class PaperCanaryCandidateStorageError(Exception):
    pass


class PaperCanaryCandidateCorruptionError(Exception):
    def __init__(self, bundle_id: str) -> None:
        super().__init__("canonical candidate evidence is corrupt")
        self.bundle_id = bundle_id


@dataclass(frozen=True, slots=True)
class CanonicalPaperCandidate:
    bundle_id: str
    idempotency_key: str
    event_timestamp: datetime
    created_at: datetime
    trading_date: date
    spot_price: float

    def __post_init__(self) -> None:
        for name in ("bundle_id", "idempotency_key"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        for name in ("event_timestamp", "created_at"):
            value = getattr(self, name)
            if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if type(self.spot_price) not in (int, float) or float(self.spot_price) <= 0:
            raise ValueError("spot_price must be positive")


class CanonicalPaperCandidateRepository(Protocol):
    def list_candidates(
        self,
        *,
        evaluated_at: datetime,
        maximum_age_seconds: float,
        limit: int,
    ) -> tuple[CanonicalPaperCandidate, ...]: ...


def _aware(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception as exc:
        raise PaperCanaryCandidateStorageError(f"invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PaperCanaryCandidateStorageError(f"naive {field}")
    return parsed


class SQLiteCanonicalPaperCandidateRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)

    def list_candidates(
        self,
        *,
        evaluated_at: datetime,
        maximum_age_seconds: float,
        limit: int,
    ) -> tuple[CanonicalPaperCandidate, ...]:
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        bounded = max(1, min(int(limit), 50))
        maximum_age = max(0.0, float(maximum_age_seconds))
        try:
            connection = sqlite3.connect(
                f"file:{self.database_path.resolve().as_posix()}?mode=ro",
                uri=True,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=5000")
            rows = connection.execute(
                """
                SELECT b.bundle_id,b.idempotency_key,b.evaluation_timestamp,
                       b.first_persisted_at,b.trading_date
                FROM canonical_red_bar_v2_bundles b
                LEFT JOIN canonical_red_bar_v2_paper_commands c
                  ON c.idempotency_key=b.idempotency_key
                WHERE c.execution_id IS NULL
                ORDER BY b.evaluation_timestamp ASC,b.bundle_id ASC
                LIMIT ?
                """,
                (bounded,),
            ).fetchall()
            candidates: list[CanonicalPaperCandidate] = []
            for row in rows:
                bundle_id = str(row["bundle_id"])
                try:
                    verified = verify_canonical_bundle_evidence(
                        connection,
                        bundle_id=bundle_id,
                    )
                except CanonicalPersistenceCorruptionError as exc:
                    raise PaperCanaryCandidateCorruptionError(bundle_id) from exc
                bundle = verified.bundle
                if bundle.strategy_id != "RED_BAR_V2":
                    raise PaperCanaryCandidateCorruptionError(bundle_id)
                event_timestamp = bundle.evaluation_timestamp
                age = (
                    evaluated_at.astimezone(timezone.utc)
                    - event_timestamp.astimezone(timezone.utc)
                ).total_seconds()
                if age < 0 or age > maximum_age:
                    continue
                reference = bundle.decision.reference
                if reference is None or float(reference.midpoint) <= 0:
                    raise PaperCanaryCandidateCorruptionError(bundle_id)
                candidates.append(
                    CanonicalPaperCandidate(
                        bundle_id=bundle.bundle_id,
                        idempotency_key=bundle.idempotency_key,
                        event_timestamp=event_timestamp,
                        created_at=bundle.created_at,
                        trading_date=bundle.trading_date,
                        spot_price=float(reference.midpoint),
                    )
                )
            return tuple(candidates)
        except PaperCanaryCandidateCorruptionError:
            raise
        except (sqlite3.Error, OSError) as exc:
            raise PaperCanaryCandidateStorageError(
                "canonical candidate database unavailable"
            ) from exc
        finally:
            try:
                connection.close()
            except UnboundLocalError:
                pass
