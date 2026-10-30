from __future__ import annotations

import argparse
import cProfile
import hashlib
import json
import pstats
import shutil
import time
from datetime import date
from pathlib import Path
from typing import Any

from .historical_replay_day_v1_1 import run_day

MODEL = "HISTORICAL_REPLAY_PERFORMANCE_PROBE_V1"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_baseline(
    session_date: date,
    *,
    replay_root: str | Path = "data/live-observation/replay",
    baseline_root: str | Path = "data/live-observation/replay-baseline-v1",
) -> dict[str, Any]:
    src = Path(replay_root) / session_date.isoformat()
    if not src.exists():
        raise FileNotFoundError(f"Completed replay directory not found: {src}")

    status_path = src / "replay-status.json"
    if not status_path.exists():
        raise FileNotFoundError(f"Replay status not found: {status_path}")

    status = json.loads(status_path.read_text(encoding="utf-8"))
    if status.get("status") != "COMPLETE":
        raise RuntimeError(f"Baseline replay is not COMPLETE: {status.get('status')}")

    dst = Path(baseline_root) / session_date.isoformat()
    dst.mkdir(parents=True, exist_ok=True)

    files = {}
    for name in ("replay-status.json", "events.jsonl", "health.jsonl", "step-audit.jsonl"):
        p = src / name
        if not p.exists():
            continue
        target = dst / name
        shutil.copy2(p, target)
        files[name] = {
            "bytes": p.stat().st_size,
            "sha256": sha256_file(p),
        }

    manifest = {
        "model": MODEL,
        "kind": "BASELINE_SNAPSHOT",
        "session_date": session_date.isoformat(),
        "source": str(src),
        "destination": str(dst),
        "files": files,
        "status_summary": {
            "checkpoint_count": status.get("checkpoint_count"),
            "processed_checkpoint_count": status.get("processed_checkpoint_count"),
            "missing_checkpoint_count": status.get("missing_checkpoint_count"),
            "observation_count": status.get("observation_count"),
            "state_counts": status.get("state_counts"),
            "step_audit_rows": status.get("step_audit_rows"),
            "step_audit_chain_ok": status.get("step_audit_chain_ok"),
        },
    }
    (dst / "baseline-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def profile_replay(
    session_date: date,
    *,
    output_root: str | Path = "data/live-observation/replay-profile-v1",
    cache_root: str | Path = "data/live-observation/replay-cache",
    profile_root: str | Path = "data/live-observation/replay-profile-v1/profiles",
    limit: int = 80,
) -> dict[str, Any]:
    profile_root = Path(profile_root)
    profile_root.mkdir(parents=True, exist_ok=True)
    prof_path = profile_root / f"{session_date.isoformat()}.prof"
    txt_path = profile_root / f"{session_date.isoformat()}-top.txt"
    json_path = profile_root / f"{session_date.isoformat()}-summary.json"

    profiler = cProfile.Profile()
    started = time.perf_counter()
    profiler.enable()
    try:
        result = run_day(
            session_date,
            output_root=output_root,
            cache_root=cache_root,
            overwrite=True,
            progress=False,
        )
    finally:
        profiler.disable()
    elapsed = time.perf_counter() - started
    profiler.dump_stats(str(prof_path))

    with txt_path.open("w", encoding="utf-8") as f:
        stats = pstats.Stats(profiler, stream=f)
        stats.strip_dirs().sort_stats("cumulative").print_stats(limit)
        f.write("\n\n===== TOP BY INTERNAL TIME =====\n")
        stats.sort_stats("tottime").print_stats(limit)

    summary = {
        "model": MODEL,
        "kind": "CPROFILE_REPLAY",
        "session_date": session_date.isoformat(),
        "elapsed_seconds": elapsed,
        "profile_path": str(prof_path),
        "report_path": str(txt_path),
        "output_root": str(output_root),
        "replay_result": result,
    }
    json_path.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("baseline")
    b.add_argument("--date", required=True)

    p = sub.add_parser("profile")
    p.add_argument("--date", required=True)
    p.add_argument("--limit", type=int, default=80)

    args = parser.parse_args()
    d = date.fromisoformat(args.date)

    if args.command == "baseline":
        result = snapshot_baseline(d)
    else:
        result = profile_replay(d, limit=args.limit)

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
