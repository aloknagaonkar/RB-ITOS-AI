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

MODEL = "HISTORICAL_OI_BUILD_JOB_V1_2"
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


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _quality(payload: dict[str, Any]) -> dict[str, Any]:
    sessions = payload.get("sessions") or []
    session = sessions[0] if len(sessions) == 1 else {}
    rows = session.get("rows") or []

    instrument_pair_rows = 0
    oi_pair_rows = 0
    premium_pair_rows = 0
    five_min_available_rows = 0

    for row in rows:
        if row.get("ce_instrument_key") and row.get("pe_instrument_key"):
            instrument_pair_rows += 1
        if row.get("ce_open_interest") is not None and row.get("pe_open_interest") is not None:
            oi_pair_rows += 1
        if row.get("ce_close") is not None and row.get("pe_close") is not None:
            premium_pair_rows += 1
        if row.get("ce_5m_state") not in (None, "UNAVAILABLE") or row.get("pe_5m_state") not in (None, "UNAVAILABLE"):
            five_min_available_rows += 1

    total = len(rows)
    return {
        "top_level_available_session_count": payload.get("available_session_count"),
        "session_status": session.get("status"),
        "session_row_count": session.get("row_count"),
        "total_rows": total,
        "instrument_pair_rows": instrument_pair_rows,
        "oi_pair_rows": oi_pair_rows,
        "premium_pair_rows": premium_pair_rows,
        "five_min_available_rows": five_min_available_rows,
        "instrument_pair_pct": (instrument_pair_rows / total * 100.0) if total else 0.0,
        "oi_pair_pct": (oi_pair_rows / total * 100.0) if total else 0.0,
        "premium_pair_pct": (premium_pair_rows / total * 100.0) if total else 0.0,
    }


def _attempt_result(paths: dict[str, Path], returncode: int) -> dict[str, Any]:
    payload = _read_json(paths["positioning_json"])
    quality = _quality(payload)
    return {
        "returncode": returncode,
        "provider_status": payload.get("status"),
        "requested_session_count": payload.get("session_count") or payload.get("requested_session_count"),
        "available_session_count": payload.get("available_session_count"),
        "row_count": payload.get("row_count"),
        "provenance": payload.get("provenance"),
        "positioning_json_exists": paths["positioning_json"].exists(),
        "positioning_csv_exists": paths["positioning_csv"].exists(),
        "quality": quality,
    }


def _complete(result: dict[str, Any]) -> bool:
    q = result.get("quality") or {}
    return (
        result.get("returncode") == 0
        and result.get("positioning_csv_exists") is True
        and q.get("top_level_available_session_count") == 1
        and q.get("session_status") == "AVAILABLE"
        and (q.get("instrument_pair_rows") or 0) > 0
        and (q.get("oi_pair_rows") or 0) > 0
        and (q.get("premium_pair_rows") or 0) > 0
    )


def _bad_contract_data(result: dict[str, Any]) -> bool:
    q = result.get("quality") or {}
    return (
        result.get("returncode") == 0
        and q.get("session_status") == "AVAILABLE"
        and (q.get("instrument_pair_rows") or 0) == 0
        and (q.get("oi_pair_rows") or 0) == 0
        and (q.get("premium_pair_rows") or 0) == 0
    )


def run_job(*, job_id: str, session_date: str, expiry: str, attempts: int = DEFAULT_ATTEMPTS) -> int:
    sd, ex = validate_request(session_date, expiry)
    paths = build_paths(session_date)
    paths["root"].mkdir(parents=True, exist_ok=True)

    # A different expiry must not reuse an old session cache built for the wrong contract set.
    paths["manifest"].write_text(
        json.dumps({"sessions": [{"session_date": sd.isoformat(), "expiry": ex.isoformat()}]}, indent=2) + "\n",
        encoding="utf-8",
    )

    started = datetime.now(timezone.utc).isoformat()
    base = {
        "model": MODEL, "job_id": job_id, "session_date": sd.isoformat(), "expiry": ex.isoformat(),
        "started_at": started, "completed_at": None, "pid": os.getpid(), "max_attempts": attempts,
        "artifacts": {k: str(v) for k, v in paths.items() if k != "root"},
    }
    history: list[dict[str, Any]] = []

    try:
        for attempt in range(1, attempts + 1):
            _write(paths["status"], {**base, "status":"RUNNING", "attempt":attempt, "attempt_history":history, "next_retry_seconds":None, "result":history[-1] if history else None, "error":None})

            with paths["log"].open("a", encoding="utf-8") as log:
                log.write(f"\n===== ATTEMPT {attempt}/{attempts} {datetime.now(timezone.utc).isoformat()} =====\n")
                proc = subprocess.run(build_command(session_date, expiry), stdout=log, stderr=subprocess.STDOUT, text=True, check=False)

            result = _attempt_result(paths, proc.returncode)
            result["attempt"] = attempt
            history.append(result)

            if _complete(result):
                _write(paths["status"], {**base, "status":"COMPLETE", "attempt":attempt, "attempt_history":history, "next_retry_seconds":None, "completed_at":datetime.now(timezone.utc).isoformat(), "result":result, "error":None})
                return 0

            # This is deterministic bad contract selection, not a transient provider miss.
            if _bad_contract_data(result):
                _write(paths["status"], {
                    **base,
                    "status":"INVALID_CONTRACT_DATA",
                    "attempt":attempt,
                    "attempt_history":history,
                    "next_retry_seconds":None,
                    "completed_at":datetime.now(timezone.utc).isoformat(),
                    "result":result,
                    "error":"Sidecar created the session envelope but found zero CE/PE instruments, premiums and OI. Verify the exact expiry for this session; retrying the same expiry will not fix it.",
                })
                return 3

            if attempt < attempts:
                delay = DEFAULT_RETRY_DELAYS_SECONDS[min(attempt - 1, len(DEFAULT_RETRY_DELAYS_SECONDS)-1)]
                _write(paths["status"], {**base, "status":"RETRYING", "attempt":attempt, "attempt_history":history, "next_retry_seconds":delay, "result":result, "error":None})
                time.sleep(delay)

        final = history[-1] if history else {}
        _write(paths["status"], {
            **base,
            "status":"PARTIAL",
            "attempt":attempts,
            "attempt_history":history,
            "next_retry_seconds":None,
            "completed_at":datetime.now(timezone.utc).isoformat(),
            "result":final,
            "error":"Historical positioning did not reach usable CE/PE instrument + premium + OI coverage after all retry attempts.",
        })
        return 2
    except Exception as exc:
        _write(paths["status"], {**base, "status":"FAILED", "attempt":len(history)+1, "attempt_history":history, "next_retry_seconds":None, "completed_at":datetime.now(timezone.utc).isoformat(), "result":history[-1] if history else None, "error":f"{type(exc).__name__}: {exc}", "traceback":traceback.format_exc()})
        return 1


def main() -> None:
    p=argparse.ArgumentParser(description=MODEL)
    p.add_argument("--job-id", required=True)
    p.add_argument("--session-date", required=True)
    p.add_argument("--expiry", required=True)
    p.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    a=p.parse_args()
    raise SystemExit(run_job(job_id=a.job_id, session_date=a.session_date, expiry=a.expiry, attempts=a.attempts))

if __name__ == "__main__":
    main()
