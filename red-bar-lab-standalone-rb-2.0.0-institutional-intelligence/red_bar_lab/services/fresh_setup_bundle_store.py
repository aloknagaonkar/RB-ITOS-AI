from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


@dataclass(frozen=True)
class FreshSetupBundleStore:
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

    def append_many_once(
        self,
        records: Iterable[Mapping[str, object]],
    ) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing = {
            str(row.get("bundle_id") or "")
            for row in self.read_all()
        }
        inserted = 0
        with self.path.open("a", encoding="utf-8") as handle:
            for record in records:
                payload = dict(record)
                payload["execution_allowed"] = False
                bundle_id = str(payload.get("bundle_id") or "")
                if bundle_id in existing:
                    continue
                handle.write(
                    json.dumps(payload, sort_keys=True, default=str) + "\n"
                )
                existing.add(bundle_id)
                inserted += 1
        return inserted

    def latest(self, limit: int = 100) -> list[dict[str, object]]:
        rows = self.read_all()
        rows.sort(
            key=lambda row: str(row.get("detected_at") or ""),
            reverse=True,
        )
        return rows[: max(1, int(limit))]
