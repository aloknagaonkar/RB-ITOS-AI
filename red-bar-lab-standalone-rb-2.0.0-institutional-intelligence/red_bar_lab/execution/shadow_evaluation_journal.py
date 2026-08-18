from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from threading import RLock
from typing import Mapping, Sequence
from uuid import uuid4


SHADOW_EVALUATION_JOURNAL_VERSION = "SHADOW-EVALUATION-JOURNAL-V1"
_LOCK = RLock()


def _journal_path(runs_root: Path | str) -> Path:
    path = Path(runs_root) / "shadow_architecture" / "evaluation_journal.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def append_evaluation_cycle(
    runs_root: Path | str,
    row: Mapping[str, object],
) -> dict[str, object]:
    """Append one restart-safe architecture evaluation cycle.

    The journal is audit-only. It does not reserve capital, consume bundles,
    create positions, mutate execution queues, or submit orders.
    """
    payload = deepcopy(dict(row))
    payload.setdefault("evaluation_id", f"EVAL-{uuid4().hex[:20].upper()}")
    payload.setdefault("recorded_at", datetime.now().astimezone().isoformat())
    payload["journal_version"] = SHADOW_EVALUATION_JOURNAL_VERSION
    payload["source_read_only"] = True
    payload["capital_reserved"] = False
    payload["bundle_consumed"] = False
    payload["position_created"] = False
    payload["order_created"] = False
    payload["order_submitted"] = False

    path = _journal_path(runs_root)
    with _LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, default=str, sort_keys=True) + "\n")
    return payload


def read_evaluation_cycles(
    runs_root: Path | str,
    *,
    limit: int = 1000,
    strategy_id: str | None = None,
    trading_date: str | None = None,
) -> list[dict[str, object]]:
    path = _journal_path(runs_root)
    if not path.exists():
        return []
    with _LOCK:
        lines = path.read_text(encoding="utf-8").splitlines()

    rows: list[dict[str, object]] = []
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if strategy_id and str(row.get("strategy_id") or "") != strategy_id:
            continue
        if trading_date and str(row.get("trading_date") or "") != trading_date:
            continue
        rows.append(row)
        if len(rows) >= max(1, int(limit)):
            break
    return rows


def summarize_evaluation_cycles(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    copied = [dict(row) for row in rows]
    by_strategy: dict[str, int] = {}
    by_terminal: dict[str, int] = {}
    routed = 0
    healthy = 0
    for row in copied:
        strategy = str(row.get("strategy_id") or "UNKNOWN")
        terminal = str(row.get("terminal_section") or "UNKNOWN")
        by_strategy[strategy] = by_strategy.get(strategy, 0) + 1
        by_terminal[terminal] = by_terminal.get(terminal, 0) + 1
        if str(row.get("section_10d_outcome") or "") == "ROUTED_SHADOW_ONLY":
            routed += 1
        if str(row.get("section_9_outcome") or "") == "SHADOW_HANDOFF_READY_DISABLED":
            healthy += 1
    return {
        "cycle_count": len(copied),
        "healthy_candidate_count": healthy,
        "shadow_routed_count": routed,
        "strategy_counts": by_strategy,
        "terminal_section_counts": by_terminal,
        "latest_recorded_at": copied[0].get("recorded_at") if copied else None,
        "journal_version": SHADOW_EVALUATION_JOURNAL_VERSION,
        "source_read_only": True,
    }


__all__ = [
    "SHADOW_EVALUATION_JOURNAL_VERSION",
    "append_evaluation_cycle",
    "read_evaluation_cycles",
    "summarize_evaluation_cycles",
]
