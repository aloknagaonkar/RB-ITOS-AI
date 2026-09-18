from __future__ import annotations
import argparse, json, os, traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from filelock import FileLock, Timeout

MODEL = "HISTORICAL_REPLAY_OPERATIONS_WORKER_V1"

def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)

def _base(job_id: str, action: str, session_date: date) -> dict[str, Any]:
    return {"model": MODEL, "job_id": job_id, "action": action,
            "session_date": session_date.isoformat(), "pid": os.getpid()}

def run_job(*, job_id: str, action: str, session_date: date,
            status_path: Path, overwrite: bool = False) -> int:
    lock_path = Path("data/live-observation/replay-jobs/locks") / f"{session_date.isoformat()}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    try:
        with FileLock(str(lock_path), timeout=0):
            _write(status_path, {**_base(job_id, action, session_date),
                "status":"RUNNING","started_at":started,"completed_at":None,
                "result":None,"error":None})
            if action == "DOWNLOAD_MISSING":
                from .historical_replay_data_v1 import download_missing, readiness
                result = {"download": download_missing(session_date),
                          "readiness_after_download": readiness(session_date)}
            elif action == "RUN_REPLAY":
                from .historical_replay_day_v1_1 import run_day
                result = run_day(session_date, overwrite=overwrite, progress=False)
            else:
                raise ValueError(f"Unsupported action: {action}")
            _write(status_path, {**_base(job_id, action, session_date),
                "status":"COMPLETE","started_at":started,
                "completed_at":datetime.now(timezone.utc).isoformat(),
                "result":result,"error":None})
            return 0
    except Timeout:
        _write(status_path, {**_base(job_id, action, session_date),
            "status":"FAILED","started_at":started,
            "completed_at":datetime.now(timezone.utc).isoformat(),
            "result":None,
            "error":f"Another replay/download job already holds the lock for {session_date.isoformat()}"})
        return 2
    except Exception as exc:
        _write(status_path, {**_base(job_id, action, session_date),
            "status":"FAILED","started_at":started,
            "completed_at":datetime.now(timezone.utc).isoformat(),
            "result":None,"error":f"{type(exc).__name__}: {exc}",
            "traceback":traceback.format_exc()})
        return 1

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--action", required=True, choices=("DOWNLOAD_MISSING","RUN_REPLAY"))
    parser.add_argument("--date", required=True)
    parser.add_argument("--status-path", required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    raise SystemExit(run_job(job_id=args.job_id, action=args.action,
        session_date=date.fromisoformat(args.date), status_path=Path(args.status_path),
        overwrite=bool(args.overwrite)))

if __name__ == "__main__":
    main()
