from __future__ import annotations
import argparse, json, os, subprocess, sys, traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

MODEL = "HISTORICAL_OI_BUILD_JOB_V1"
ROOT = Path("data/historical-evidence/historical-oi-build")

def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)

def validate_request(session_date: str, expiry: str) -> tuple[date, date]:
    sd = date.fromisoformat(session_date)
    ex = date.fromisoformat(expiry)
    if ex < sd:
        raise ValueError("Expiry cannot be before session date.")
    return sd, ex

def build_paths(session_date: str) -> dict[str, Path]:
    root = ROOT / session_date
    return {
        "root": root,
        "manifest": root / "manifest.json",
        "positioning_json": root / "positioning.json",
        "positioning_csv": root / "positioning.csv",
        "cache_dir": root / "positioning-cache",
        "status": root / "build-status.json",
        "log": root / "build.log",
    }

def build_command(session_date: str, expiry: str) -> list[str]:
    paths = build_paths(session_date)
    return [
        sys.executable, "-m", "market_lab.historical_positioning_sidecar",
        "--underlying", "NSE_INDEX|Nifty 50",
        "--manifest", str(paths["manifest"]),
        "--wings", "5",
        "--cache-dir", str(paths["cache_dir"]),
        "--output", str(paths["positioning_json"]),
        "--csv-output", str(paths["positioning_csv"]),
    ]

def run_job(*, job_id: str, session_date: str, expiry: str) -> int:
    sd, ex = validate_request(session_date, expiry)
    paths = build_paths(session_date)
    paths["root"].mkdir(parents=True, exist_ok=True)
    paths["manifest"].write_text(
        json.dumps({"sessions":[{"session_date":sd.isoformat(),"expiry":ex.isoformat()}]}, indent=2) + "\n",
        encoding="utf-8",
    )
    started = datetime.now(timezone.utc).isoformat()
    base = {
        "model": MODEL, "job_id": job_id, "session_date": sd.isoformat(), "expiry": ex.isoformat(),
        "started_at": started, "completed_at": None, "pid": os.getpid(),
        "artifacts": {
            "manifest": str(paths["manifest"]),
            "positioning_json": str(paths["positioning_json"]),
            "positioning_csv": str(paths["positioning_csv"]),
            "log": str(paths["log"]),
        },
    }
    _write(paths["status"], {**base, "status":"RUNNING", "result":None, "error":None})
    try:
        with paths["log"].open("w", encoding="utf-8") as log:
            proc = subprocess.run(build_command(session_date, expiry), stdout=log, stderr=subprocess.STDOUT, text=True, check=False)
        result = {
            "returncode": proc.returncode,
            "positioning_json_exists": paths["positioning_json"].exists(),
            "positioning_csv_exists": paths["positioning_csv"].exists(),
        }
        if paths["positioning_json"].exists():
            try:
                payload = json.loads(paths["positioning_json"].read_text(encoding="utf-8"))
                result.update({
                    "status": payload.get("status"),
                    "requested_session_count": payload.get("session_count") or payload.get("requested_session_count"),
                    "available_session_count": payload.get("available_session_count"),
                    "row_count": payload.get("row_count"),
                    "provenance": payload.get("provenance"),
                })
            except (OSError, json.JSONDecodeError):
                pass
        if proc.returncode != 0:
            raise RuntimeError(f"Historical positioning build failed with exit code {proc.returncode}. See {paths['log']}")
        if not paths["positioning_csv"].exists():
            raise RuntimeError("Historical positioning build completed without positioning CSV output.")
        _write(paths["status"], {**base, "status":"COMPLETE", "completed_at":datetime.now(timezone.utc).isoformat(), "result":result, "error":None})
        return 0
    except Exception as exc:
        _write(paths["status"], {**base, "status":"FAILED", "completed_at":datetime.now(timezone.utc).isoformat(), "result":None, "error":f"{type(exc).__name__}: {exc}", "traceback":traceback.format_exc()})
        return 1

def main() -> None:
    p = argparse.ArgumentParser(description=MODEL)
    p.add_argument("--job-id", required=True)
    p.add_argument("--session-date", required=True)
    p.add_argument("--expiry", required=True)
    a = p.parse_args()
    raise SystemExit(run_job(job_id=a.job_id, session_date=a.session_date, expiry=a.expiry))

if __name__ == "__main__":
    main()
