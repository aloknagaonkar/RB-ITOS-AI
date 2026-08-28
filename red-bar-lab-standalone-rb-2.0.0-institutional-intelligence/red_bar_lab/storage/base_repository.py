"""Base repository class for domain-specific database access."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


class BaseRepository:
    """Base class providing shared database connection logic."""

    def __init__(self, path: Path, initialize_lock: threading.Lock | None = None) -> None:
        self.path = Path(path)
        self._initialize_lock = initialize_lock or threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _query(
        self,
        sql: str,
        params: tuple = (),
        *,
        fetch: bool = True,
    ) -> list[dict[str, object]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall() if fetch else []
            return [dict(row) for row in rows]

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._connect() as conn:
            result = conn.execute(sql, params)
            conn.commit()
            return result

    def _executescript(self, script: str) -> None:
        with self._connect() as conn:
            conn.executescript(script)
