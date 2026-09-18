from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import Snapshot
from .storage import Observation

MODEL = "HISTORICAL_REPLAY_SNAPSHOT_INDEX_V1"


def _dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


@dataclass(frozen=True)
class IndexedRawSnapshot:
    received_at: datetime
    raw: dict[str, Any]


class HistoricalReplaySnapshotIndexV1:
    """Load one session's snapshot JSON once and binary-search by received_at.

    The live production selector is intentionally left unchanged. This class is
    used only by accelerated historical replay.
    """

    def __init__(
        self,
        rows: list[IndexedRawSnapshot],
        *,
        parse_fn: Callable[[dict[str, Any]], Any] = Snapshot.model_validate,
        tolerance_seconds: int = 30,
    ):
        self.rows = sorted(rows, key=lambda r: r.received_at)
        self.times = [r.received_at for r in self.rows]
        self.parse_fn = parse_fn
        self.tolerance = timedelta(seconds=tolerance_seconds)
        self._parsed: dict[int, Any] = {}

    @classmethod
    def load(
        cls,
        engine,
        config_id: int,
        session_date: date,
        *,
        tolerance_seconds: int = 30,
    ) -> "HistoricalReplaySnapshotIndexV1":
        # Select only the snapshot JSON column. Do not ORM-load Observation rows,
        # because that would also decode the large evaluation JSON column.
        with Session(engine) as session:
            raw_snapshots = session.scalars(
                select(Observation.snapshot).where(
                    Observation.config_id == config_id,
                    Observation.session_date == session_date.isoformat(),
                ).order_by(Observation.id)
            ).all()

        rows = []
        for raw in raw_snapshots:
            received = raw.get("received_at")
            if not received:
                continue
            rows.append(IndexedRawSnapshot(_dt(received), raw))

        return cls(rows, tolerance_seconds=tolerance_seconds)

    def select_first_at_or_after(self, checkpoint: datetime):
        if not self.rows:
            return None

        i = bisect_left(self.times, checkpoint)
        if i >= len(self.rows):
            return None

        row = self.rows[i]
        delta = row.received_at - checkpoint
        if delta < timedelta(0) or delta > self.tolerance:
            return None

        if i not in self._parsed:
            self._parsed[i] = self.parse_fn(row.raw)
        return self._parsed[i]

    @property
    def raw_count(self) -> int:
        return len(self.rows)

    @property
    def parsed_count(self) -> int:
        return len(self._parsed)
