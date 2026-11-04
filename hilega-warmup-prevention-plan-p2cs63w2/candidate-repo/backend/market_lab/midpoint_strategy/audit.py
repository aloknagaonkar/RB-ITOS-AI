from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    session_date: str
    strategy: str
    version: str
    family: str
    event_timestamp: str
    event_type: str

    direction: Optional[str] = None
    state_before: Optional[str] = None
    state_after: Optional[str] = None
    result: Optional[str] = None
    reason: Optional[str] = None

    underlying_price: Optional[float] = None
    directional_points: Optional[float] = None

    reference_type: Optional[str] = None
    reference_high: Optional[float] = None
    reference_low: Optional[float] = None
    midpoint: Optional[float] = None
    original_boundary: Optional[float] = None

    futures_price: Optional[float] = None
    futures_vwap: Optional[float] = None
    directional_vwap_value: Optional[float] = None

    source_candle_timestamp: Optional[str] = None
    evidence: Mapping[str, Any] = field(default_factory=dict)

    observation_only: bool = True
    execution_enabled: bool = False
    paper_order_enabled: bool = False
    quantity: None = None


def deterministic_event_id(
    *,
    session_date: str,
    family: str,
    event_timestamp: str,
    event_type: str,
    direction: Optional[str],
    ordinal: int = 0,
) -> str:
    raw = "|".join([
        session_date,
        family,
        event_timestamp,
        event_type,
        direction or "",
        str(ordinal),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


class JsonlAuditJournal:
    """Append-only audit journal.

    The writer never edits previous rows. Duplicate event_ids are ignored,
    making replay/restart idempotent for deterministic lifecycle events.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seen = set()
        if self.path.exists():
            with self.path.open() as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        self._seen.add(json.loads(line)["event_id"])
                    except Exception:
                        # Do not mutate a damaged historical journal.
                        raise ValueError(f"invalid audit JSONL: {self.path}")

    def append(self, event: AuditEvent) -> bool:
        if event.event_id in self._seen:
            return False
        row = asdict(event)
        with self.path.open("a") as fh:
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()
        self._seen.add(event.event_id)
        return True

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = []
        with self.path.open() as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows
