from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

from .historical_replay_day_v1_1 import run_day as run_day_v1_1
from .historical_replay_snapshot_index_v1 import HistoricalReplaySnapshotIndexV1
from . import live_shadow_production_wiring_v1 as wiring

MODEL = "HISTORICAL_REPLAY_ENGINE_V1_2"
OPTIMIZER = "SESSION_SNAPSHOT_INDEX_V1"


@contextmanager
def _indexed_snapshot_selector():
    original = wiring.select_first_snapshot_at_or_after
    indexes: dict[tuple[int, int, str], HistoricalReplaySnapshotIndexV1] = {}

    def select_indexed(engine, config_id, checkpoint):
        key = (id(engine), int(config_id), checkpoint.date().isoformat())
        index = indexes.get(key)
        if index is None:
            index = HistoricalReplaySnapshotIndexV1.load(
                engine,
                int(config_id),
                checkpoint.date(),
            )
            indexes[key] = index
        return index.select_first_at_or_after(checkpoint)

    wiring.select_first_snapshot_at_or_after = select_indexed
    try:
        yield indexes
    finally:
        wiring.select_first_snapshot_at_or_after = original


def run_day(
    session_date: date,
    *,
    output_root: str | Path = "data/live-observation/replay-v1-2",
    cache_root: str | Path = "data/live-observation/replay-cache",
    overwrite: bool = False,
    progress: bool = True,
) -> dict[str, Any]:
    with _indexed_snapshot_selector() as indexes:
        result = run_day_v1_1(
            session_date,
            output_root=output_root,
            cache_root=cache_root,
            overwrite=overwrite,
            progress=progress,
        )

        stats = {
            "optimizer_model": OPTIMIZER,
            "index_count": len(indexes),
            "indexed_snapshot_count": sum(x.raw_count for x in indexes.values()),
            "parsed_snapshot_count": sum(x.parsed_count for x in indexes.values()),
        }

    return {
        **result,
        "performance_wrapper_model": MODEL,
        "performance": stats,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--output-root", default="data/live-observation/replay-v1-2")
    parser.add_argument("--cache-root", default="data/live-observation/replay-cache")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--no-progress", action="store_true")
    args = parser.parse_args()

    result = run_day(
        date.fromisoformat(args.date),
        output_root=args.output_root,
        cache_root=args.cache_root,
        overwrite=args.overwrite,
        progress=not args.no_progress,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
