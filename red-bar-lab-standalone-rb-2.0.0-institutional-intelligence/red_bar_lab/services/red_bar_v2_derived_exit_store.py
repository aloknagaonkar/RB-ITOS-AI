"""Where a session records the exits its own policy resolved.

Two jobs, and the second is the one that pays for the table.

*Continuity.* A live cycle replays the whole session every pass. The replay's one
route from ACTIVE to CLOSED is the exits it is handed, so a resolved exit that is
not carried across cycles is a resolved exit that never happened: the next pass
starts from an empty list, the trade row is open again, and every later candidate
is refused ``ACTIVE_TRADE_BLOCK``. Persisting one row per settled entry is what
lets the cycles act as the iteration -- one entry settled per pass, no pass
re-deriving what an earlier one already knew.

*Answering "why is it flat".* Each row carries the reason, the level and the
R-multiple the policy closed on. Before this, that verdict existed only inside a
research call and nothing in production could be asked when a position came off.

Rows are keyed by ``(trading_date, instrument_key, entry_timestamp)`` and written
once. That an exit never moves once resolved is not an assumption here -- it is
the monotonicity property the resolver asserts on every pass: an exit at 10:00
cannot change any decision before 10:00, so the prefix it was derived from is
fixed. A conflicting write is therefore a bug worth surfacing rather than an
update to apply, and the insert says so.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS red_bar_v2_derived_exits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_date TEXT NOT NULL,
    instrument_key TEXT NOT NULL,
    entry_timestamp TEXT NOT NULL,
    resolved_at TEXT NOT NULL,
    trade_id TEXT,
    direction TEXT,
    exit_timestamp TEXT,
    fed_at TEXT NOT NULL,
    exit_reason TEXT,
    entry_price REAL,
    exit_price REAL,
    stop_price REAL,
    risk_points REAL,
    points REAL,
    r_multiple REAL,
    holding_minutes REAL,
    rejection TEXT,
    rejection_detail TEXT,
    UNIQUE(trading_date, instrument_key, entry_timestamp)
);
CREATE INDEX IF NOT EXISTS idx_v2_derived_exits_session
ON red_bar_v2_derived_exits(trading_date, instrument_key, entry_timestamp);
"""


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _float_or_none(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def persist_red_bar_v2_derived_exit(
    database_path: str | Path,
    *,
    trading_date: str,
    instrument_key: str,
    exit: Any,
    resolved_at: datetime | str | None = None,
) -> int:
    """Record one settled entry. Returns 0 if the row was already there.

    ``exit`` is a ``DerivedExit`` whose ``fed_at`` is set -- an entry the policy
    actually took off, or one that could not be given a risk plan and so was
    closed at its own entry bar. An exit still open on the data available has no
    ``fed_at`` and is not settled; writing it would freeze a verdict the next
    candle can still change, so it is refused here rather than guarded at each
    call site.
    """
    fed_at = _iso(getattr(exit, "fed_at", None))
    if fed_at is None:
        raise ValueError(
            "refusing to record a derived exit with no fed_at: the position is "
            "still open on the data available, so its exit is not settled"
        )
    entry_timestamp = _iso(getattr(exit, "entry_timestamp", None))
    if entry_timestamp is None:
        raise ValueError("a derived exit must carry the entry timestamp it settles")

    outcome = getattr(exit, "outcome", None)
    plan = getattr(exit, "plan", None)
    exit_reason = getattr(getattr(outcome, "exit_reason", None), "value", None)

    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    values = (
        str(trading_date),
        str(instrument_key),
        entry_timestamp,
        _iso(resolved_at) or datetime.now().astimezone().isoformat(),
        _iso(getattr(exit, "trade_id", None)),
        _iso(getattr(exit, "direction", None)),
        _iso(getattr(exit, "exit_timestamp", None)),
        fed_at,
        exit_reason,
        _float_or_none(getattr(plan, "entry_price", None)),
        _float_or_none(getattr(outcome, "exit_price", None)),
        _float_or_none(getattr(plan, "stop_price", None)),
        _float_or_none(getattr(plan, "risk_points", None)),
        _float_or_none(getattr(outcome, "points", None)),
        _float_or_none(getattr(outcome, "r_multiple", None)),
        _float_or_none(getattr(outcome, "holding_minutes", None)),
        _iso(getattr(exit, "rejection", None)),
        _iso(getattr(exit, "rejection_detail", None)),
    )
    with sqlite3.connect(path) as connection:
        connection.executescript(_SCHEMA)
        cursor = connection.execute(
            """
            INSERT INTO red_bar_v2_derived_exits (
                trading_date,instrument_key,entry_timestamp,resolved_at,trade_id,
                direction,exit_timestamp,fed_at,exit_reason,entry_price,exit_price,
                stop_price,risk_points,points,r_multiple,holding_minutes,
                rejection,rejection_detail
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(trading_date,instrument_key,entry_timestamp) DO NOTHING
            """,
            values,
        )
        connection.commit()
        return int(cursor.lastrowid or 0) if cursor.rowcount else 0


def read_red_bar_v2_derived_exits(
    database_path: str | Path,
    *,
    trading_date: str,
    instrument_key: str | None = None,
) -> list[dict[str, Any]]:
    """Settled exits for one session, earliest entry first. Creates nothing."""
    path = Path(database_path)
    if not path.exists():
        return []
    clauses = ["trading_date=?"]
    params: list[Any] = [str(trading_date)]
    if instrument_key:
        clauses.append("instrument_key=?")
        params.append(str(instrument_key))
    try:
        with sqlite3.connect(path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM red_bar_v2_derived_exits "
                f"WHERE {' AND '.join(clauses)} ORDER BY entry_timestamp",
                params,
            ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return []
        raise
    return [dict(row) for row in rows]


__all__ = [
    "persist_red_bar_v2_derived_exit",
    "read_red_bar_v2_derived_exits",
]
