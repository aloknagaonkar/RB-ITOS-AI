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

MODEL = "HISTORICAL_OI_BUILD_JOB_V1_3"
ROOT = Path("data/historical-evidence/historical-oi-build")
DEFAULT_ATTEMPTS = 3
DEFAULT_RETRY_DELAYS_SECONDS = (15, 60)
RESEARCH_WINGS = 5


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


def build_command(session_date: str, expiry: str, *, wings: int = RESEARCH_WINGS) -> list[str]:
    paths = build_paths(session_date)
    return [
        sys.executable, "-m", "market_lab.historical_positioning_sidecar",
        "--underlying", "NSE_INDEX|Nifty 50",
        "--manifest", str(paths["manifest"]),
        "--wings", str(wings),
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
    for row in rows:
        if row.get("ce_instrument_key") and row.get("pe_instrument_key"):
            instrument_pair_rows += 1
        if row.get("ce_open_interest") is not None and row.get("pe_open_interest") is not None:
            oi_pair_rows += 1
        if row.get("ce_close") is not None and row.get("pe_close") is not None:
            premium_pair_rows += 1

    total = len(rows)
    return {
        "top_level_available_session_count": payload.get("available_session_count"),
        "session_status": session.get("status"),
        "session_row_count": session.get("row_count"),
        "session_wings": session.get("wings"),
        "total_rows": total,
        "instrument_pair_rows": instrument_pair_rows,
        "oi_pair_rows": oi_pair_rows,
        "premium_pair_rows": premium_pair_rows,
        "instrument_pair_pct": (instrument_pair_rows / total * 100.0) if total else 0.0,
        "oi_pair_pct": (oi_pair_rows / total * 100.0) if total else 0.0,
        "premium_pair_pct": (premium_pair_rows / total * 100.0) if total else 0.0,
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


def _required_union_wings(payload: dict[str, Any]) -> dict[str, Any]:
    sessions = payload.get("sessions") or []
    if len(sessions) != 1:
        return {"required_wings": RESEARCH_WINGS, "fixed_atm": None, "max_atm_offset_strikes": 0}
    session = sessions[0]
    rows = session.get("rows") or []
    if not rows:
        return {"required_wings": RESEARCH_WINGS, "fixed_atm": None, "max_atm_offset_strikes": 0}

    by_ts: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_ts.setdefault(str(row.get("timestamp")), []).append(row)

    morning_key = next((k for k in sorted(by_ts) if "T09:20:" in k), None)
    if morning_key is None:
        return {"required_wings": RESEARCH_WINGS, "fixed_atm": None, "max_atm_offset_strikes": 0}

    fixed_atm = float(by_ts[morning_key][0]["moving_atm"])
    strike_interval = float(session.get("strike_interval") or 50.0)
    moving_atms = {
        float(group[0]["moving_atm"])
        for group in by_ts.values()
        if group and group[0].get("moving_atm") is not None
    }
    max_offset = max(
        (int(round(abs(atm - fixed_atm) / strike_interval)) for atm in moving_atms),
        default=0,
    )
    return {
        "required_wings": RESEARCH_WINGS + max_offset,
        "fixed_atm": fixed_atm,
        "max_atm_offset_strikes": max_offset,
        "strike_interval": strike_interval,
    }


def _run_sidecar(paths, session_date: str, expiry: str, *, wings: int, log):
    proc = subprocess.run(
        build_command(session_date, expiry, wings=wings),
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return proc.returncode, _read_json(paths["positioning_json"])


def _attempt_result(paths: dict[str, Path], returncode: int) -> dict[str, Any]:
    payload = _read_json(paths["positioning_json"])
    return {
        "returncode": returncode,
        "positioning_json_exists": paths["positioning_json"].exists(),
        "positioning_csv_exists": paths["positioning_csv"].exists(),
        "row_count": payload.get("row_count"),
        "available_session_count": payload.get("available_session_count"),
        "quality": _quality(payload),
    }


def run_job(*, job_id: str, session_date: str, expiry: str, attempts: int = DEFAULT_ATTEMPTS) -> int:
    sd, ex = validate_request(session_date, expiry)
    paths = build_paths(session_date)
    paths["root"].mkdir(parents=True, exist_ok=True)
    paths["manifest"].write_text(
        json.dumps({"sessions": [{"session_date": sd.isoformat(), "expiry": ex.isoformat()}]}, indent=2) + "\n",
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
        "artifacts": {k: str(v) for k, v in paths.items() if k != "root"},
    }
    history: list[dict[str, Any]] = []

    try:
        for attempt in range(1, attempts + 1):
            _write(paths["status"], {
                **base, "status": "RUNNING", "attempt": attempt,
                "attempt_history": history, "next_retry_seconds": None,
                "result": history[-1] if history else None, "error": None,
            })

            with paths["log"].open("a", encoding="utf-8") as log:
                log.write(f"\n===== ATTEMPT {attempt}/{attempts} {datetime.now(timezone.utc).isoformat()} =====\n")

                rc, first_payload = _run_sidecar(
                    paths, session_date, expiry, wings=RESEARCH_WINGS, log=log
                )

                coverage = _required_union_wings(first_payload)
                required_wings = int(coverage["required_wings"])

                if rc == 0 and required_wings > RESEARCH_WINGS:
                    log.write(
                        f"\n===== UNION COVERAGE EXPANSION "
                        f"wings={RESEARCH_WINGS}->{required_wings}; "
                        f"fixed_atm={coverage.get('fixed_atm')}; "
                        f"max_atm_offset_strikes={coverage.get('max_atm_offset_strikes')} =====\n"
                    )
                    rc, _ = _run_sidecar(
                        paths, session_date, expiry, wings=required_wings, log=log
                    )

            result = _attempt_result(paths, rc)
            result["attempt"] = attempt
            result["research_wings"] = RESEARCH_WINGS
            result["raw_sidecar_wings"] = required_wings
            result["union_coverage"] = coverage
            history.append(result)

            if _complete(result):
                _write(paths["status"], {
                    **base, "status": "COMPLETE", "attempt": attempt,
                    "attempt_history": history, "next_retry_seconds": None,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "result": result, "error": None,
                })
                return 0

            if _bad_contract_data(result):
                _write(paths["status"], {
                    **base, "status": "INVALID_CONTRACT_DATA", "attempt": attempt,
                    "attempt_history": history, "next_retry_seconds": None,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "result": result,
                    "error": "Zero usable CE/PE instruments, premiums and OI. Verify exact expiry.",
                })
                return 3

            if attempt < attempts:
                delay = DEFAULT_RETRY_DELAYS_SECONDS[min(attempt - 1, len(DEFAULT_RETRY_DELAYS_SECONDS) - 1)]
                _write(paths["status"], {
                    **base, "status": "RETRYING", "attempt": attempt,
                    "attempt_history": history, "next_retry_seconds": delay,
                    "result": result, "error": None,
                })
                time.sleep(delay)

        _write(paths["status"], {
            **base, "status": "PARTIAL", "attempt": attempts,
            "attempt_history": history, "next_retry_seconds": None,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "result": history[-1] if history else None,
            "error": "Historical positioning did not become complete after all attempts.",
        })
        return 2
    except Exception as exc:
        _write(paths["status"], {
            **base, "status": "FAILED", "attempt": len(history) + 1,
            "attempt_history": history, "next_retry_seconds": None,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "result": history[-1] if history else None,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })
        return 1


def main() -> None:
    p = argparse.ArgumentParser(description=MODEL)
    p.add_argument("--job-id", required=True)
    p.add_argument("--session-date", required=True)
    p.add_argument("--expiry", required=True)
    p.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    a = p.parse_args()
    raise SystemExit(run_job(
        job_id=a.job_id, session_date=a.session_date, expiry=a.expiry, attempts=a.attempts
    ))


if __name__ == "__main__":
    main()
