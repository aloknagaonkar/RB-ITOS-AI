from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import sqlite3

from .models import OptionOiCell


@dataclass(frozen=True, slots=True)
class NormalizedChainSnapshot:
    underlying: str
    provider: str
    source_timestamp: datetime
    spot: float
    expiry: date
    cells: tuple[OptionOiCell, ...]


class OptionParticipationSnapshotSource:
    """Read one already-normalized option snapshot; never calls a provider."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def latest(self, *, underlying: str) -> NormalizedChainSnapshot | None:
        if not self.database_path.exists(): return None
        try:
            with sqlite3.connect(self.database_path) as connection:
                connection.row_factory = sqlite3.Row
                stamp = connection.execute(
                    """SELECT observed_at FROM option_participation_snapshots
                       WHERE underlying_name=?
                       ORDER BY julianday(observed_at) DESC, observed_at DESC LIMIT 1""",
                    (underlying,),
                ).fetchone()
                if stamp is None: return None
                rows = connection.execute(
                    """SELECT observed_at, underlying_name, spot_price, expiry,
                              option_type, instrument_key, strike, oi, prev_oi, payload_json
                       FROM option_participation_snapshots
                       WHERE underlying_name=? AND observed_at=?
                       ORDER BY strike, option_type""",
                    (underlying, stamp["observed_at"]),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower(): return None
            raise
        if not rows: return None
        source_timestamp = datetime.fromisoformat(str(rows[0]["observed_at"]))
        if source_timestamp.tzinfo is None: raise ValueError("SOURCE_TIMESTAMP_NAIVE")
        expiry = date.fromisoformat(str(rows[0]["expiry"]))
        spot = float(rows[0]["spot_price"])
        cells: list[OptionOiCell] = []
        for row in rows:
            if row["instrument_key"] is None or row["strike"] is None or row["oi"] is None:
                continue
            cells.append(OptionOiCell(
                instrument_key=str(row["instrument_key"]),
                option_side=str(row["option_type"]),
                strike=float(row["strike"]),
                expiry=expiry,
                current_oi=float(row["oi"]),
                provider_prev_oi=None if row["prev_oi"] is None else float(row["prev_oi"]),
                source_timestamp=source_timestamp,
            ))
        return NormalizedChainSnapshot(underlying, "UPSTOX", source_timestamp, spot, expiry, tuple(cells))
