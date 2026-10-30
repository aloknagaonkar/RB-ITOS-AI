from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

MODEL = "HISTORICAL_OI_BUILD_JOB_V1_1"
ROOT = Path("data/historical-evidence/historical-oi-build")
DEFAULT_ATTEMPTS = 3
DEFAULT_RETRY_DELAYS_SECONDS = (15, 60)


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


def _read_result_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _attempt_result(paths: dict[str, Path], returncode: int) -> dict[str, Any]:
    payload = _read_result_json(paths["positioning_json"])
    return {
        "returncode": returncode,
        "provider_status": payload.get("status"),
        "requested_session_count": payload.get("session_count") or payload.get("requested_session_count"),
        "available_session_count": payload.get("available_session_count"),
        "unavailable_session_count": payload.get("unavailable_session_count"),
        "row_count": payload.get("row_count"),
        "provenance": payload.get("provenance"),
        "positioning_json_exists": paths["positioning_json"].exists(),
        "positioning_csv_exists": paths["positioning_csv"].exists(),
    }


def _complete(result: dict[str, Any]) -> bool:
    return (
        result.get("returncode") == 0
        and result.get("provider_status") == "AVAILABLE"
        and result.get("positioning_csv_exists") is True
    )


def run_job(
    *,
    job_id: str,
    session_date: str,
    expiry: str,
    attempts: int = DEFAULT_ATTEMPTS,
    retry_delays_seconds: tuple[int, ...] = DEFAULT_RETRY_DELAYS_SECONDS,
) -> int:
    sd, ex = validate_request(session_date, expiry)
    paths = build_paths(session_date)
    paths["root"].mkdir(parents=True, exist_ok=True)

    paths["manifest"].write_text(
        json.dumps(
            {"sessions": [{"session_date": sd.isoformat(), "expiry": ex.isoformat()}]},
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    started = datetime.now(timezone.utc).isoformat()
    base = {
        "model": MODEL,
        "job_id": job_id,
        "session_date": sd.isoformat(),
        "expiry": ex.isoformat(),
        "started_at": started,
        "completed_at": None,
        "pid": os.getpid(),
        "max_attempts": attempts,
        "artifacts": {
            "manifest": str(paths["manifest"]),
            "positioning_json": str(paths["positioning_json"]),
            "positioning_csv": str(paths["positioning_csv"]),
            "cache_dir": str(paths["cache_dir"]),
            "log": str(paths["log"]),
        },
    }

    attempt_history: list[dict[str, Any]] = []

    try:
        for attempt in range(1, attempts + 1):
            _write(paths["status"], {
                **base,
                "status": "RUNNING",
                "attempt": attempt,
                "attempt_history": attempt_history,
                "next_retry_seconds": None,
                "result": attempt_history[-1] if attempt_history else None,
                "error": None,
            })

            with paths["log"].open("a", encoding="utf-8") as log:
                log.write(f"\n===== ATTEMPT {attempt}/{attempts} {datetime.now(timezone.utc).isoformat()} =====\n")
                proc = subprocess.run(
                    build_command(session_date, expiry),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                )

            result = _attempt_result(paths, proc.returncode)
            result["attempt"] = attempt
            attempt_history.append(result)

            if _complete(result):
                _write(paths["status"], {
                    **base,
                    "status": "COMPLETE",
                    "attempt": attempt,
                    "attempt_history": attempt_history,
                    "next_retry_seconds": None,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "result": result,
                    "error": None,
                })
                return 0

            if attempt < attempts:
                delay_index = min(attempt - 1, len(retry_delays_seconds) - 1)
                delay = retry_delays_seconds[delay_index]
                _write(paths["status"], {
                    **base,
                    "status": "RETRYING",
                    "attempt": attempt,
                    "attempt_history": attempt_history,
                    "next_retry_seconds": delay,
                    "result": result,
                    "error": None,
                })
                time.sleep(delay)

        final = attempt_history[-1] if attempt_history else {}
        status = "PARTIAL" if final.get("provider_status") == "PARTIAL" else "FAILED"
        _write(paths["status"], {
            **base,
            "status": status,
            "attempt": attempts,
            "attempt_history": attempt_history,
            "next_retry_seconds": None,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "result": final,
            "error": None if status == "PARTIAL" else "Historical positioning did not become AVAILABLE after all retry attempts.",
        })
        return 2 if status == "PARTIAL" else 1

    except Exception as exc:
        _write(paths["status"], {
            **base,
            "status": "FAILED",
            "attempt": len(attempt_history) + 1,
            "attempt_history": attempt_history,
            "next_retry_seconds": None,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "result": attempt_history[-1] if attempt_history else None,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description=MODEL)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--session-date", required=True)
    parser.add_argument("--expiry", required=True)
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    args = parser.parse_args()
    raise SystemExit(run_job(
        job_id=args.job_id,
        session_date=args.session_date,
        expiry=args.expiry,
        attempts=args.attempts,
    ))


if __name__ == "__main__":
    main()
