from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .domain import PCRConfig
from .storage import Configuration, Observation

MODEL = "HISTORICAL_REPLAY_EQUIVALENT_MULTICONFIG_SESSION_V1"
_NON_SEMANTIC_FIELDS = {"name", "interval_seconds"}


def replay_semantic_payload(payload: dict[str, Any]) -> dict[str, Any]:
    config = PCRConfig.model_validate(payload)
    value = config.model_dump(mode="json")
    for key in _NON_SEMANTIC_FIELDS:
        value.pop(key, None)
    return value


def session_config_counts(engine, session_date: date) -> list[tuple[int, int]]:
    with Session(engine) as session:
        rows = session.execute(
            select(Observation.config_id, func.count(Observation.id))
            .where(Observation.session_date == session_date.isoformat())
            .group_by(Observation.config_id)
            .order_by(Observation.config_id)
        ).all()
    return [(int(config_id), int(count)) for config_id, count in rows]


def resolve_session_config_ids(engine, session_date: date) -> list[int]:
    counts = session_config_counts(engine, session_date)
    if not counts:
        raise RuntimeError(f"No stored observations for {session_date}")

    config_ids = [config_id for config_id, _ in counts]
    if len(config_ids) == 1:
        return config_ids

    with Session(engine) as session:
        configs = {
            config_id: session.get(Configuration, config_id)
            for config_id in config_ids
        }

    missing = [config_id for config_id, row in configs.items() if row is None]
    if missing:
        raise RuntimeError(
            "Historical session configuration rows are missing; fail-closed: "
            + ", ".join(str(x) for x in missing)
        )

    normalized = {
        config_id: replay_semantic_payload(configs[config_id].payload)
        for config_id in config_ids
    }
    baseline_id = config_ids[0]
    baseline = normalized[baseline_id]

    incompatible: list[str] = []
    for config_id in config_ids[1:]:
        current = normalized[config_id]
        if current == baseline:
            continue
        differing = sorted(
            key for key in set(baseline) | set(current)
            if baseline.get(key) != current.get(key)
        )
        incompatible.append(
            f"{baseline_id} vs {config_id}: " + ",".join(differing)
        )

    if incompatible:
        raise RuntimeError(
            "Historical session contains replay-incompatible configuration IDs; "
            "fail-closed instead of merging: "
            + "; ".join(incompatible)
        )

    return config_ids


def resolve_session_config_id(engine, session_date: date) -> int:
    return resolve_session_config_ids(engine, session_date)[-1]
