from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


@dataclass(frozen=True)
class SignalTradeAttributionStore:
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

    def _write_all(self, rows: Iterable[Mapping[str, object]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            for row in rows:
                payload = dict(row)
                payload["execution_allowed"] = False
                handle.write(
                    json.dumps(payload, sort_keys=True, default=str) + "\n"
                )

    def upsert(self, record: Mapping[str, object]) -> bool:
        payload = dict(record)
        payload["execution_allowed"] = False
        ledger_id = str(payload.get("ledger_id") or "")
        if not ledger_id:
            raise ValueError("Attribution record requires ledger_id.")

        rows = self.read_all()
        updated = False
        found = False
        output = []
        for row in rows:
            if str(row.get("ledger_id") or "") == ledger_id:
                found = True
                if row != payload:
                    output.append(payload)
                    updated = True
                else:
                    output.append(row)
            else:
                output.append(row)

        if not found:
            output.append(payload)
            updated = True

        if updated:
            self._write_all(output)
        return updated

    def get(self, ledger_id: str) -> dict[str, object] | None:
        for row in self.read_all():
            if str(row.get("ledger_id") or "") == ledger_id:
                return row
        return None

    def by_bundle(self, bundle_id: str) -> dict[str, object] | None:
        for row in self.read_all():
            if str(row.get("bundle_id") or "") == bundle_id:
                return row
        return None

    def latest(self, limit: int = 100) -> list[dict[str, object]]:
        rows = self.read_all()
        rows.sort(
            key=lambda row: str(
                row.get("exit_time")
                or row.get("entry_time")
                or row.get("detected_at")
                or ""
            ),
            reverse=True,
        )
        return rows[: max(1, int(limit))]
