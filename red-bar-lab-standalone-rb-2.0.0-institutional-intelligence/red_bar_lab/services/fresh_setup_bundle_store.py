from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


def canonical_bundle_identity(
    record: Mapping[str, object],
) -> tuple[str, str, str, str]:
    return (
        str(record.get("instrument_key") or ""),
        str(record.get("detected_at") or ""),
        str(record.get("direction") or ""),
        str(record.get("primary_setup_type") or ""),
    )


@dataclass(frozen=True)
class FreshSetupBundleStore:
    path: Path

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

    def append_many_once(
        self,
        records: Iterable[Mapping[str, object]],
    ) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing_rows = self.read_all()
        existing_ids = {
            str(row.get("bundle_id") or "")
            for row in existing_rows
        }
        existing_canonical = {
            canonical_bundle_identity(row)
            for row in existing_rows
        }

        inserted = 0
        with self.path.open("a", encoding="utf-8") as handle:
            for record in records:
                payload = dict(record)
                payload["execution_allowed"] = False
                bundle_id = str(payload.get("bundle_id") or "")
                canonical = canonical_bundle_identity(payload)

                if bundle_id in existing_ids or canonical in existing_canonical:
                    continue

                handle.write(
                    json.dumps(payload, sort_keys=True, default=str) + "\n"
                )
                existing_ids.add(bundle_id)
                existing_canonical.add(canonical)
                inserted += 1
        return inserted

    def canonical_rows(self) -> list[dict[str, object]]:
        """Return one canonical row per logical setup.

        Prefer manually generated rows over historical backfill rows when both
        represent the same instrument/time/direction/setup.
        """
        selected: dict[
            tuple[str, str, str, str],
            dict[str, object],
        ] = {}
        for row in self.read_all():
            key = canonical_bundle_identity(row)
            current = selected.get(key)
            if current is None:
                selected[key] = row
                continue
            current_backfill = bool(current.get("historical_backfill"))
            row_backfill = bool(row.get("historical_backfill"))
            if current_backfill and not row_backfill:
                selected[key] = row
        rows = list(selected.values())
        rows.sort(key=lambda row: str(row.get("detected_at") or ""))
        return rows

    def latest(self, limit: int = 100) -> list[dict[str, object]]:
        rows = self.canonical_rows()
        rows.sort(
            key=lambda row: str(row.get("detected_at") or ""),
            reverse=True,
        )
        return rows[: max(1, int(limit))]
