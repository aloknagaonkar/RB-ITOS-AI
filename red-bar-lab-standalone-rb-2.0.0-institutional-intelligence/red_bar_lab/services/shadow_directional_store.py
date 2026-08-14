from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


@dataclass(frozen=True)
class ShadowDirectionalStore:
    """Append-only observation store for Sprint 4.2 shadow decisions."""

    path: Path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    @staticmethod
    def record_key(record: Mapping[str, object]) -> tuple[str, str]:
        return (
            str(record.get("instrument_key") or ""),
            str(record.get("timestamp") or record.get("candle_timestamp") or ""),
        )

    def read_all(self) -> list[dict[str, object]]:
        self.initialize()
        rows: list[dict[str, object]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    item = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    rows.append(item)
        return rows

    def append_once(self, record: Mapping[str, object]) -> bool:
        """Persist one instrument+candle decision once.

        Returns True when inserted and False when the same completed candle was
        already evaluated. No trade or execution tables are touched.
        """
        self.initialize()
        payload = dict(record)
        payload["execution_allowed"] = False
        key = self.record_key(payload)
        if not all(key):
            raise ValueError("Shadow record requires instrument_key and timestamp.")

        existing = {self.record_key(row) for row in self.read_all()}
        if key in existing:
            return False

        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
        return True

    def latest(
        self,
        *,
        instrument_key: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        rows = self.read_all()
        if instrument_key:
            rows = [
                row for row in rows
                if str(row.get("instrument_key") or "") == instrument_key
            ]
        rows.sort(
            key=lambda row: str(
                row.get("timestamp") or row.get("candle_timestamp") or ""
            ),
            reverse=True,
        )
        return rows[: max(1, int(limit))]
