from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


@dataclass(frozen=True)
class FreshSetupSignalStore:
    path: Path

    @staticmethod
    def identity(record: Mapping[str, object]) -> tuple[str, str, str]:
        return (
            str(record.get("transition_id") or ""),
            str(record.get("setup_type") or ""),
            str(record.get("detected_at") or ""),
        )

    def read_all(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, object]] = []
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

    def resolve_many_once(
        self,
        records: Iterable[Mapping[str, object]],
    ) -> tuple[list[dict[str, object]], int]:
        """Return canonical persisted rows, inserting only missing identities."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing_rows = self.read_all()
        canonical = {
            self.identity(row): row
            for row in existing_rows
        }

        resolved: list[dict[str, object]] = []
        inserted = 0

        with self.path.open("a", encoding="utf-8") as handle:
            for record in records:
                payload = dict(record)
                payload["execution_allowed"] = False
                key = self.identity(payload)

                if key in canonical:
                    resolved.append(dict(canonical[key]))
                    continue

                handle.write(
                    json.dumps(payload, sort_keys=True, default=str) + "\n"
                )
                canonical[key] = payload
                resolved.append(dict(payload))
                inserted += 1

        return resolved, inserted

    def append_many_once(
        self,
        records: Iterable[Mapping[str, object]],
    ) -> int:
        _, inserted = self.resolve_many_once(records)
        return inserted

    def latest(self, limit: int = 100) -> list[dict[str, object]]:
        rows = self.read_all()
        rows.sort(
            key=lambda row: str(row.get("detected_at") or ""),
            reverse=True,
        )
        return rows[: max(1, int(limit))]

    def counts_by_type(self) -> list[dict[str, object]]:
        counts: dict[str, int] = {}
        for row in self.read_all():
            setup_type = str(row.get("setup_type") or "UNKNOWN")
            counts[setup_type] = counts.get(setup_type, 0) + 1
        return [
            {
                "setup_type": setup_type,
                "generated": count,
                "execution_allowed": False,
            }
            for setup_type, count in sorted(counts.items())
        ]
