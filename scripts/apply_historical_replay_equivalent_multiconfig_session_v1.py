from pathlib import Path

DAY = Path("backend/market_lab/historical_replay_day_v1_1.py")
INDEX = Path("backend/market_lab/historical_replay_snapshot_index_v1.py")

day = DAY.read_text(encoding="utf-8")
index = INDEX.read_text(encoding="utf-8")

old_resolver = """def resolve_session_config_id(engine, session_date: date) -> int:
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
"""

new_resolver = """def resolve_session_config_ids(engine, session_date: date) -> list[int]:
    from .historical_replay_session_config_v1 import (
        resolve_session_config_ids as _resolve_session_config_ids,
    )
    return _resolve_session_config_ids(engine, session_date)


def resolve_session_config_id(engine, session_date: date) -> int:
    from .historical_replay_session_config_v1 import (
        resolve_session_config_id as _resolve_session_config_id,
    )
    return _resolve_session_config_id(engine, session_date)
"""

if new_resolver not in day:
    if old_resolver not in day:
        raise SystemExit("Safe-stop: historical replay config resolver block not found.")
    day = day.replace(old_resolver, new_resolver, 1)

import_anchor = "from .storage import Observation\n"
import_line = "from .historical_replay_session_config_v1 import resolve_session_config_ids\n"
if import_line not in index:
    if import_anchor not in index:
        raise SystemExit("Safe-stop: snapshot-index storage import anchor not found.")
    index = index.replace(import_anchor, import_anchor + import_line, 1)

old_query = """        with Session(engine) as session:
            raw_snapshots = session.scalars(
                select(Observation.snapshot).where(
                    Observation.config_id == config_id,
                    Observation.session_date == session_date.isoformat(),
                ).order_by(Observation.id)
            ).all()
"""

new_query = """        config_ids = resolve_session_config_ids(engine, session_date)
        if config_id not in config_ids:
            raise RuntimeError(
                f"Requested config_id {config_id} is not part of "
                f"{session_date} replay-equivalent session configs {config_ids}"
            )

        with Session(engine) as session:
            raw_snapshots = session.scalars(
                select(Observation.snapshot).where(
                    Observation.config_id.in_(config_ids),
                    Observation.session_date == session_date.isoformat(),
                ).order_by(Observation.id)
            ).all()
"""

if new_query not in index:
    if old_query not in index:
        raise SystemExit("Safe-stop: snapshot-index query block not found.")
    index = index.replace(old_query, new_query, 1)

DAY.write_text(day, encoding="utf-8")
INDEX.write_text(index, encoding="utf-8")
print("Applied equivalent multi-config historical replay session support.")
