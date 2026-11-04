from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_audit_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with Path(path).open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def validate_audit_monotonicity(rows: list[dict[str, Any]]) -> None:
    last = None
    seen = set()
    for row in rows:
        eid = row["event_id"]
        if eid in seen:
            raise AssertionError(f"duplicate audit event_id: {eid}")
        seen.add(eid)

        ts = row["event_timestamp"]
        if last is not None and ts < last:
            raise AssertionError(
                f"non-monotonic audit timestamps: {last} -> {ts}"
            )
        last = ts

        if row["observation_only"] is not True:
            raise AssertionError("audit safety violation: observation_only")
        if row["execution_enabled"] is not False:
            raise AssertionError("audit safety violation: execution_enabled")
        if row["paper_order_enabled"] is not False:
            raise AssertionError("audit safety violation: paper_order_enabled")
        if row["quantity"] is not None:
            raise AssertionError("audit safety violation: quantity")
