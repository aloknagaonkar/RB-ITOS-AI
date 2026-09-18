from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .domain import IST
from .historical_replay_data_v1 import readiness
from .historical_replay_sources_v1 import HistoricalReplayMarketSourcesV1
from .live_shadow_production_wiring_v1 import LiveShadowProductionCoordinatorV1
from .storage import Observation, initialize, make_engine

MODEL = "HISTORICAL_REPLAY_ENGINE_V1_1"
FIRST_CHECKPOINT = time(9, 20)
LAST_CHECKPOINT = time(15, 25)
LAST_RUNTIME_TICK = time(15, 31)
ACTIVE_RUNTIME_STATES = {"OPTION_RESOLVED", "OPEN", "BE_ARMED", "TRAIL_ARMED"}


def _session_dt(session_date: date, value: time) -> datetime:
    return datetime.combine(session_date, value, tzinfo=IST)


def replay_dir(
    session_date: date,
    root: str | Path = "data/live-observation/replay",
) -> Path:
    return Path(root) / session_date.isoformat()


def resolve_session_config_id(engine, session_date: date) -> int:
    with Session(engine) as session:
        rows = session.execute(
            select(Observation.config_id, func.count(Observation.id))
            .where(Observation.session_date == session_date.isoformat())
            .group_by(Observation.config_id)
            .order_by(Observation.config_id)
        ).all()

    if not rows:
        raise RuntimeError(f"No stored observations for {session_date}")
    if len(rows) != 1:
        raise RuntimeError(
            "Historical session contains multiple configuration IDs; "
            "fail-closed instead of guessing: "
            + ", ".join(f"{config_id}:{count}" for config_id, count in rows)
        )
    return int(rows[0][0])


class HistoricalEventTimeAuditProxyV1:
    def __init__(self, store):
        self.store = store

    def append(
        self,
        *,
        event_time,
        checkpoint,
        stage,
        status,
        payload=None,
        observation_id=None,
    ):
        payload = payload or {}
        historical = checkpoint
        for key in (
            "bar_timestamp",
            "entry_timestamp",
            "expected_entry_timestamp",
        ):
            if historical is None and payload.get(key):
                historical = datetime.fromisoformat(payload[key]).astimezone(IST)
        if historical is None:
            historical = event_time
        return self.store.append(
            event_time=historical,
            checkpoint=checkpoint,
            stage=stage,
            status=status,
            payload=payload,
            observation_id=observation_id,
        )

    def read_all(self):
        return self.store.read_all()

    def verify_chain(self):
        return self.store.verify_chain()


def _jsonable(value: Any):
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _state_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value).astimezone(IST)


def _next_due_for_state(state, after: datetime) -> datetime | None:
    """
    Earliest historical clock time at which the unchanged production
    process_entries_and_open_trades(now) can make new progress.

    OPTION_RESOLVED:
      confirmation T -> entry timestamp T+1 -> production first evaluates
      exact next-minute open at T+2. If still unresolved (missing exact bar),
      retry one minute later so production can mark it incomplete.

    OPEN/BE_ARMED/TRAIL_ARMED:
      if previous processed option bar is P, next bar is P+1 and becomes
      completed at P+2. If no bar has been processed, P is the entry timestamp.
    """
    status = state.status
    if status == "OPTION_RESOLVED":
        confirmation = _state_dt(state.confirmation_timestamp)
        if confirmation is None:
            return None
        first_due = confirmation + timedelta(minutes=2)
        if first_due > after:
            return first_due
        return after + timedelta(minutes=1)

    if status in {"OPEN", "BE_ARMED", "TRAIL_ARMED"}:
        previous = _state_dt(state.last_bar_timestamp) or _state_dt(state.entry_timestamp)
        if previous is None:
            return None
        due = previous + timedelta(minutes=2)
        if due > after:
            return due
        return after + timedelta(minutes=1)

    return None


def _next_runtime_due(coordinator, after: datetime) -> datetime | None:
    states = coordinator.adapter.states()
    due = [
        value
        for state in states.values()
        if state.status in ACTIVE_RUNTIME_STATES
        for value in [_next_due_for_state(state, after)]
        if value is not None
    ]
    return min(due) if due else None


def _advance_runtime_until(
    coordinator,
    *,
    after: datetime,
    limit: datetime,
    progress: bool,
) -> datetime:
    cursor = after
    guard = 0

    while True:
        due = _next_runtime_due(coordinator, cursor)
        if due is None or due > limit:
            return cursor

        coordinator.process_entries_and_open_trades(due)
        cursor = due
        guard += 1

        if progress:
            active = [
                f"{oid}:{state.status}"
                for oid, state in coordinator.adapter.states().items()
                if state.status in ACTIVE_RUNTIME_STATES
            ]
            suffix = ", ".join(active) if active else "none"
            print(
                f"[runtime {due.strftime('%H:%M')}] active={suffix}",
                flush=True,
            )

        # A trade has a 15m max hold. This is merely a loop-safety guard,
        # not a trading rule.
        if guard > 250:
            raise RuntimeError(
                "Historical replay runtime scheduler exceeded safety guard"
            )


def run_day(
    session_date: date,
    *,
    output_root: str | Path = "data/live-observation/replay",
    cache_root: str | Path = "data/live-observation/replay-cache",
    overwrite: bool = False,
    progress: bool = True,
) -> dict[str, Any]:
    load_dotenv(".env")
    engine = make_engine()
    initialize(engine)

    ready = readiness(
        session_date,
        engine=engine,
        cache_root=cache_root,
    )
    if not ready["checkpoint_analysis_ready"]:
        raise RuntimeError(
            f"Checkpoint analysis data not ready for {session_date}"
        )
    if not ready["full_replay_prerequisites_ready"]:
        raise RuntimeError(
            "Full replay prerequisites are not ready. Run: "
            f"python -m market_lab.historical_replay_data_v1 "
            f"--date {session_date} download-missing"
        )

    config_id = resolve_session_config_id(engine, session_date)

    out = replay_dir(session_date, output_root)
    if out.exists():
        if not overwrite:
            raise RuntimeError(
                f"Replay output already exists: {out}. "
                "Use --overwrite to intentionally replace this historical replay."
            )
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    events_path = out / "events.jsonl"
    health_path = out / "health.jsonl"
    step_audit_path = out / "step-audit.jsonl"
    status_path = out / "replay-status.json"
    checkpoints_path = out / "checkpoints.json"

    sources = HistoricalReplayMarketSourcesV1(
        session_date,
        cache_root=cache_root,
    )
    coordinator = LiveShadowProductionCoordinatorV1(
        engine=engine,
        config_id=config_id,
        market_sources=sources,
        events_path=events_path,
        health_path=health_path,
        step_audit_path=step_audit_path,
    )
    coordinator.step_audit = HistoricalEventTimeAuditProxyV1(
        coordinator.step_audit
    )

    first = _session_dt(session_date, FIRST_CHECKPOINT)
    last = _session_dt(session_date, LAST_CHECKPOINT)
    last_tick = _session_dt(session_date, LAST_RUNTIME_TICK)

    status = {
        "model": MODEL,
        "session_date": session_date.isoformat(),
        "status": "RUNNING",
        "config_id": config_id,
        "first_checkpoint": first.isoformat(),
        "last_checkpoint": last.isoformat(),
        "execution_enabled": False,
        "paper_order_enabled": False,
        "observation_only": True,
        "scheduler": "EVENT_DRIVEN_RUNTIME_V1",
        "events_path": str(events_path),
        "health_path": str(health_path),
        "step_audit_path": str(step_audit_path),
    }
    status_path.write_text(json.dumps(status, indent=2))

    if progress:
        print(
            f"Replay {session_date} | EVENT_DRIVEN_RUNTIME_V1 | "
            "execution=DISABLED",
            flush=True,
        )

    checkpoint_results = []
    checkpoint = first
    runtime_cursor = first - timedelta(minutes=1)

    while checkpoint <= last:
        # Preserve runtime events that are due before this 5m checkpoint.
        runtime_cursor = _advance_runtime_until(
            coordinator,
            after=runtime_cursor,
            limit=checkpoint - timedelta(microseconds=1),
            progress=progress,
        )

        result = coordinator.process_checkpoint(checkpoint)
        checkpoint_results.append(result)

        if progress:
            print(
                f"[checkpoint {checkpoint.strftime('%H:%M')}] "
                f"status={result.get('status')} "
                f"all3={result.get('all3', '-')}"
                f" observation={result.get('observation_id') or '-'}",
                flush=True,
            )

        # Runtime work that becomes due exactly at checkpoint is processed
        # after checkpoint analysis, matching live worker ordering.
        runtime_cursor = _advance_runtime_until(
            coordinator,
            after=runtime_cursor,
            limit=checkpoint,
            progress=progress,
        )

        checkpoint += timedelta(minutes=5)

    _advance_runtime_until(
        coordinator,
        after=runtime_cursor,
        limit=last_tick,
        progress=progress,
    )

    states = coordinator.adapter.states()
    counts: dict[str, int] = {}
    trades = []
    for oid, state in states.items():
        counts[state.status] = counts.get(state.status, 0) + 1
        trades.append({
            "observation_id": oid,
            **{
                key: _jsonable(value)
                for key, value in vars(state).items()
            },
        })

    chain_ok, chain_issue = coordinator.step_audit.verify_chain()
    audit_rows = coordinator.step_audit.read_all()

    status.update({
        "status": "COMPLETE",
        "checkpoint_count": len(checkpoint_results),
        "processed_checkpoint_count": sum(
            1 for row in checkpoint_results
            if row.get("status") == "PROCESSED"
        ),
        "missing_checkpoint_count": sum(
            1 for row in checkpoint_results
            if row.get("status") == "MISSING_SNAPSHOT"
        ),
        "observation_count": len(states),
        "state_counts": counts,
        "step_audit_rows": len(audit_rows),
        "step_audit_chain_ok": chain_ok,
        "step_audit_chain_issue": chain_issue,
        "trades": trades,
    })

    checkpoints_path.write_text(
        json.dumps(checkpoint_results, indent=2, default=str)
    )
    status_path.write_text(json.dumps(status, indent=2, default=str))

    if progress:
        print(
            f"Replay COMPLETE | checkpoints={len(checkpoint_results)} "
            f"observations={len(states)} audit_rows={len(audit_rows)} "
            f"chain_ok={chain_ok}",
            flush=True,
        )

    return status


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Accelerated event-driven one-day historical replay through "
            "unchanged Live Shadow production logic"
        )
    )
    parser.add_argument("--date", required=True)
    parser.add_argument(
        "--output-root",
        default="data/live-observation/replay",
    )
    parser.add_argument(
        "--cache-root",
        default="data/live-observation/replay-cache",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    result = run_day(
        date.fromisoformat(args.date),
        output_root=args.output_root,
        cache_root=args.cache_root,
        overwrite=args.overwrite,
        progress=not args.quiet,
    )
    if args.quiet:
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
