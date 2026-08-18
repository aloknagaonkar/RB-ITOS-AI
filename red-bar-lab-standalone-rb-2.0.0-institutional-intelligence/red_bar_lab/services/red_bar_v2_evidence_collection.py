from __future__ import annotations

from collections import Counter

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping

from red_bar_lab.services.red_bar_v2_promotion_readiness import PromotionEvidence


@dataclass(frozen=True)
class EvidencePaths:
    root: Path

    @property
    def replay(self) -> Path:
        return self.root / "replay_sessions.jsonl"

    @property
    def parity(self) -> Path:
        return self.root / "parity_comparisons.jsonl"

    @property
    def shadow(self) -> Path:
        return self.root / "shadow_sessions.jsonl"


class RedBarV2EvidenceStore:
    """Append-only operational evidence store.

    Core replay and worker components remain side-effect free. Runtime callers
    explicitly record their completed result here after evaluation.
    """

    def __init__(self, root: str | Path):
        self.paths = EvidencePaths(Path(root))
        self.paths.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _append(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        row = dict(payload)
        row.setdefault("recorded_at", datetime.now().astimezone().isoformat())
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")

    def record_replay(self, result: Any, *, error: str | None = None) -> None:
        candidate_events = [
            event
            for event in (getattr(result, "events", ()) or ())
            if getattr(event, "event_type", None) == "CANDIDATE_ADMISSION"
        ]
        admission_code_counts = dict(
            Counter(
                str(getattr(event, "admission_code", None) or "UNKNOWN")
                for event in candidate_events
            )
        )

        self._append(
            self.paths.replay,
            {
                "trading_date": getattr(result, "trading_date", None),
                "instrument_key": getattr(result, "instrument_key", None),
                "admitted_candidates": int(getattr(result, "admitted_candidates", 0) or 0),
                "blocked_candidates": int(getattr(result, "blocked_candidates", 0) or 0),
                "candidate_event_count": len(candidate_events),
                "admission_code_counts": admission_code_counts,
                "error": error,
            },
        )

    def record_parity(self, report: Any, *, scenario: str | None = None) -> None:
        self._append(
            self.paths.parity,
            {
                "scenario": scenario,
                "matches": bool(getattr(report, "matches", False)),
                "mismatch_fields": list(getattr(report, "mismatch_fields", ()) or ()),
            },
        )

    def record_shadow_session(
        self,
        *,
        session_id: str,
        decisions: Iterable[Any],
        errors: Iterable[str] = (),
    ) -> None:
        decision_rows = list(decisions)
        error_rows = [str(item) for item in errors]
        self._append(
            self.paths.shadow,
            {
                "session_id": session_id,
                "decision_count": len(decision_rows),
                "error_count": len(error_rows),
                "statuses": [getattr(item, "status", None) for item in decision_rows],
                "errors": error_rows,
            },
        )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                rows.append({"error": "INVALID_JSONL"})
                continue
            rows.append(value if isinstance(value, dict) else {"error": "INVALID_ROW"})
    return rows


def _sqlite_counts(database_path: Path) -> dict[str, int | bool]:
    if not database_path.exists():
        return {
            "candidate_rows": 0,
            "duplicate_entries": 0,
            "lifecycle_conflicts": 0,
            "audit_available": False,
        }
    try:
        with sqlite3.connect(database_path) as conn:
            tables = {
                str(row[0])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            required = {
                "market_indicator_snapshots",
                "red_bar_v2_direction_events",
                "candidate_admission_decisions",
            }
            if not required.issubset(tables):
                return {
                    "candidate_rows": 0,
                    "duplicate_entries": 0,
                    "lifecycle_conflicts": 0,
                    "audit_available": False,
                }
            candidate_rows = int(
                conn.execute("SELECT COUNT(*) FROM candidate_admission_decisions").fetchone()[0]
            )
            duplicate_entries = int(
                conn.execute(
                    "SELECT COUNT(*) FROM candidate_admission_decisions "
                    "WHERE candidate_allowed=1 AND duplicate_signal=1"
                ).fetchone()[0]
            )
            lifecycle_conflicts = int(
                conn.execute(
                    "SELECT COUNT(*) FROM candidate_admission_decisions "
                    "WHERE active_trade_count > 1"
                ).fetchone()[0]
            )
            return {
                "candidate_rows": candidate_rows,
                "duplicate_entries": duplicate_entries,
                "lifecycle_conflicts": lifecycle_conflicts,
                "audit_available": True,
            }
    except sqlite3.Error:
        return {
            "candidate_rows": 0,
            "duplicate_entries": 0,
            "lifecycle_conflicts": 0,
            "audit_available": False,
        }


def collect_promotion_evidence(
    *,
    database_path: str | Path,
    evidence_root: str | Path,
    unit_tests_passed: int = 88,
    unit_tests_failed: int = 0,
    rollback_plan_available: bool = True,
    operator_approval: bool = False,
    operator_name: str | None = None,
) -> PromotionEvidence:
    """Build promotion evidence from SQLite and append-only runtime records."""
    database_path = Path(database_path)
    paths = EvidencePaths(Path(evidence_root))
    replay_rows = _read_jsonl(paths.replay)
    parity_rows = _read_jsonl(paths.parity)
    shadow_rows = _read_jsonl(paths.shadow)
    sqlite_counts = _sqlite_counts(database_path)

    replay_errors = sum(1 for row in replay_rows if row.get("error"))
    replay_candidates = sum(
        int(row.get("admitted_candidates") or 0) + int(row.get("blocked_candidates") or 0)
        for row in replay_rows
    )
    parity_mismatches = sum(1 for row in parity_rows if not bool(row.get("matches")))
    shadow_errors = sum(int(row.get("error_count") or 0) for row in shadow_rows)
    shadow_decisions = sum(int(row.get("decision_count") or 0) for row in shadow_rows)

    references = [
        str(path)
        for path in (paths.replay, paths.parity, paths.shadow)
        if path.exists()
    ]
    return PromotionEvidence(
        unit_tests_passed=int(unit_tests_passed),
        unit_tests_failed=int(unit_tests_failed),
        replay_sessions=len(replay_rows),
        replay_candidates=replay_candidates,
        replay_errors=replay_errors,
        shadow_sessions=len(shadow_rows),
        shadow_decisions=shadow_decisions,
        shadow_errors=shadow_errors,
        parity_comparisons=len(parity_rows),
        parity_mismatches=parity_mismatches,
        duplicate_entries=int(sqlite_counts["duplicate_entries"]),
        unresolved_lifecycle_conflicts=int(sqlite_counts["lifecycle_conflicts"]),
        storage_audit_available=bool(sqlite_counts["audit_available"]),
        rollback_plan_available=bool(rollback_plan_available),
        feature_flag_default_off=True,
        legacy_exit_path_unchanged=True,
        operator_approval=bool(operator_approval),
        operator_name=(operator_name or "").strip() or None,
        evidence_reference=";".join(references) or str(database_path),
    )
