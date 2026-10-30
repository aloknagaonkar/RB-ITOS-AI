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

MODEL = "HISTORICAL_REPLAY_ENGINE_V1"
FIRST_CHECKPOINT = time(9, 20)
LAST_CHECKPOINT = time(15, 25)
LAST_RUNTIME_TICK = time(15, 31)


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
        raise RuntimeError(
            f"No stored observations for {session_date}"
        )
    if len(rows) != 1:
        raise RuntimeError(
            "Historical session contains multiple configuration IDs; "
            "fail-closed instead of guessing: "
            + ", ".join(f"{config_id}:{count}" for config_id, count in rows)
        )
    return int(rows[0][0])


class HistoricalEventTimeAuditProxyV1:
    """
    Preserve the exact step-audit schema but make historical replay event_time
    meaningful. Checkpoint stages use checkpoint; option-minute/entry stages use
    their historical payload timestamp.
    """

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


def run_day(
    session_date: date,
    *,
    output_root: str | Path = "data/live-observation/replay",
    cache_root: str | Path = "data/live-observation/replay-cache",
    overwrite: bool = False,
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

    checkpoint_results = []
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
        "events_path": str(events_path),
        "health_path": str(health_path),
        "step_audit_path": str(step_audit_path),
    }
    status_path.write_text(json.dumps(status, indent=2))

    now = first
    next_checkpoint = first
    while now <= last_tick:
        if now == next_checkpoint and next_checkpoint <= last:
            result = coordinator.process_checkpoint(next_checkpoint)
            checkpoint_results.append(result)
            next_checkpoint += timedelta(minutes=5)

        coordinator.process_entries_and_open_trades(now)
        now += timedelta(minutes=1)

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
    return status


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay one historical session through live shadow logic"
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
    args = parser.parse_args()

    result = run_day(
        date.fromisoformat(args.date),
        output_root=args.output_root,
        cache_root=args.cache_root,
        overwrite=args.overwrite,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
