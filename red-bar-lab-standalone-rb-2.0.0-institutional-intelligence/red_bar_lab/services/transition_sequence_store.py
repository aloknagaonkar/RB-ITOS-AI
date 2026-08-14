from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class TransitionSequenceStore:
    path: Path

    def read_all(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows

    def latest(self) -> dict[str, object] | None:
        rows = self.read_all()
        return rows[-1] if rows else None

    def append_once(self, record: Mapping[str, object]) -> bool:
        payload = dict(record)
        payload["execution_allowed"] = False
        self.path.parent.mkdir(parents=True, exist_ok=True)

        key = (
            str(payload.get("transition_id") or ""),
            str(payload.get("updated_at") or ""),
            str(payload.get("stage") or ""),
        )
        existing = {
            (
                str(row.get("transition_id") or ""),
                str(row.get("updated_at") or ""),
                str(row.get("stage") or ""),
            )
            for row in self.read_all()
        }
        if key in existing:
            return False

        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
        return True
