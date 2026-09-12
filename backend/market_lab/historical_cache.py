"""Persistent immutable cache for reconstructed historical research sessions.

The cache stores fully reconstructed HistoricalResearchSession payloads so later
research/evidence work can run without repeating provider requests. Only AVAILABLE
sessions are written. Writes are atomic and cache identity includes the inputs that
change reconstruction semantics.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .historical_research import HistoricalResearchSession

CACHE_SCHEMA_VERSION = 1
RECONSTRUCTION_VERSION = "historical-pcr-v1"


@dataclass(frozen=True)
class HistoricalSessionCacheKey:
    underlying: str
    session_date: date
    expiry: date
    wings: int
    strike_interval: int = 50
    reconstruction_version: str = RECONSTRUCTION_VERSION

    def __post_init__(self) -> None:
        if not self.underlying:
            raise ValueError("underlying is required")
        if self.expiry < self.session_date:
            raise ValueError("expiry must be on or after session_date")
        if type(self.wings) is not int or self.wings < 0:
            raise ValueError("wings must be a non-negative integer")
        if type(self.strike_interval) is not int or self.strike_interval <= 0:
            raise ValueError("strike_interval must be a positive integer")
        if not self.reconstruction_version:
            raise ValueError("reconstruction_version is required")

    def identity(self) -> dict[str, object]:
        return {
            "underlying": self.underlying,
            "session_date": self.session_date.isoformat(),
            "expiry": self.expiry.isoformat(),
            "wings": self.wings,
            "strike_interval": self.strike_interval,
            "reconstruction_version": self.reconstruction_version,
        }

    def digest(self) -> str:
        encoded = json.dumps(self.identity(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:20]

    def filename(self) -> str:
        return f"{self.session_date.isoformat()}__{self.expiry.isoformat()}__{self.digest()}.json"


class HistoricalSessionCache:
    def __init__(self, root: str | Path = "data/historical-cache") -> None:
        self.root = Path(root)

    def path_for(self, key: HistoricalSessionCacheKey) -> Path:
        return self.root / key.filename()

    def load(self, key: HistoricalSessionCacheKey) -> HistoricalResearchSession | None:
        path = self.path_for(key)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("cache_schema_version") != CACHE_SCHEMA_VERSION:
            return None
        if payload.get("key") != key.identity():
            return None
        session = HistoricalResearchSession.model_validate(payload.get("session"))
        if session.status != "AVAILABLE":
            return None
        if (
            session.underlying != key.underlying
            or session.session_date != key.session_date
            or session.expiry != key.expiry
            or session.wings != key.wings
            or session.strike_interval != key.strike_interval
        ):
            return None
        return session

    def store(self, key: HistoricalSessionCacheKey, session: HistoricalResearchSession) -> Path:
        if session.status != "AVAILABLE" or not session.observations:
            raise ValueError("only non-empty AVAILABLE historical sessions may be cached")
        if (
            session.underlying != key.underlying
            or session.session_date != key.session_date
            or session.expiry != key.expiry
            or session.wings != key.wings
            or session.strike_interval != key.strike_interval
        ):
            raise ValueError("historical session does not match cache key")

        self.root.mkdir(parents=True, exist_ok=True)
        target = self.path_for(key)
        payload = {
            "cache_schema_version": CACHE_SCHEMA_VERSION,
            "key": key.identity(),
            "session": session.model_dump(mode="json"),
        }
        rendered = json.dumps(payload, indent=2) + "\n"

        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(rendered)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
        return target

    def remove(self, key: HistoricalSessionCacheKey) -> bool:
        path = self.path_for(key)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
