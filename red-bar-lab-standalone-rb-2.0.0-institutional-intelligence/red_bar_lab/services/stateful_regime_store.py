from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class StatefulRegimeStore:
    path: Path

    def read_all(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return rows

    def latest(self) -> dict[str, object] | None:
        rows = self.read_all()
        return rows[-1] if rows else None

    def append_once(self, record: Mapping[str, object]) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(record)
        payload["execution_allowed"] = False
        key = (str(payload.get("instrument_key")), str(payload.get("timestamp")))
        existing = {
            (str(row.get("instrument_key")), str(row.get("timestamp")))
            for row in self.read_all()
        }
        if key in existing:
            return False
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, default=str, sort_keys=True) + "\n")
        return True
