from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .historical_oi_enrichment_v1 import (
    _load_built,
    _load_canonical,
    enrich_session,
    write_csv,
)

MODEL = "HISTORICAL_OI_AUTO_ENRICHMENT_V1"
ANALYTICAL_WINGS = 5


def required_raw_wings_from_session(session: dict[str, Any], analytical_wings: int = ANALYTICAL_WINGS) -> dict[str, Any]:
    rows = session.get("rows") or []
    if not rows:
        raise ValueError("Built positioning session has no rows")

    interval = float(session.get("strike_interval") or 0)
    if interval <= 0:
        strikes = sorted({float(r["strike"]) for r in rows if r.get("strike") is not None})
        diffs = [b-a for a,b in zip(strikes, strikes[1:]) if b>a]
        if not diffs:
            raise ValueError("Cannot infer strike interval")
        interval = min(diffs)

    by_ts: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_ts.setdefault(str(r["timestamp"]), []).append(r)

    anchor_ts = None
    fixed_atm = None
    moving_atms: list[float] = []

    for ts in sorted(by_ts):
        dt = datetime.fromisoformat(ts)
        if dt.strftime("%H:%M") == "09:20":
            atms = {float(r["moving_atm"]) for r in by_ts[ts] if r.get("moving_atm") is not None}
            if len(atms) == 1:
                anchor_ts = ts
                fixed_atm = next(iter(atms))
                break

    if fixed_atm is None:
        raise ValueError("Exact 09:20 moving ATM is unavailable")

    for ts, group in sorted(by_ts.items()):
        dt = datetime.fromisoformat(ts)
        hhmm = dt.strftime("%H:%M")
        if not ("09:20" <= hhmm <= "15:25"):
            continue
        atms = {float(r["moving_atm"]) for r in group if r.get("moving_atm") is not None}
        if len(atms) == 1:
            moving_atms.append(next(iter(atms)))

    if not moving_atms:
        raise ValueError("No moving ATM checkpoints available")

    max_drift_intervals = max(
        int(round(abs(atm-fixed_atm)/interval))
        for atm in moving_atms
    )
    required = analytical_wings + max_drift_intervals

    return {
        "fixed_atm": fixed_atm,
        "anchor_timestamp": anchor_ts,
        "strike_interval": interval,
        "min_moving_atm": min(moving_atms),
        "max_moving_atm": max(moving_atms),
        "max_drift_intervals": max_drift_intervals,
        "analytical_wings": analytical_wings,
        "required_raw_wings": required,
    }


def _manifest(path: Path, session_date: str, expiry: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"sessions":[{"session_date":session_date,"expiry":expiry}]}, indent=2),
        encoding="utf-8",
    )


def _run_sidecar(
    *,
    session_date: str,
    expiry: str,
    underlying: str,
    wings: int,
    out_json: Path,
    out_csv: Path,
    cache_dir: Path,
) -> None:
    manifest = out_json.parent / f"manifest-w{wings}.json"
    _manifest(manifest, session_date, expiry)
    cmd = [
        sys.executable, "-m", "market_lab.historical_positioning_sidecar",
        "--underlying", underlying,
        "--manifest", str(manifest),
        "--wings", str(wings),
        "--cache-dir", str(cache_dir),
        "--output", str(out_json),
        "--csv-output", str(out_csv),
    ]
    completed = subprocess.run(cmd, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"historical_positioning_sidecar failed for wings={wings}")


def run_auto_enrichment(
    *,
    session_date: str,
    expiry: str,
    underlying: str = "NSE_INDEX|Nifty 50",
    canonical_path: str | Path = "data/historical-evidence/oi-pattern-library-90d-historical-only-v1.csv",
    build_root: str | Path = "data/historical-evidence/historical-oi-build",
    enrichment_root: str | Path = "data/historical-evidence/historical-oi-enrichment",
) -> dict[str, Any]:
    build_dir = Path(build_root) / session_date
    build_dir.mkdir(parents=True, exist_ok=True)

    phase_a_json = build_dir / "positioning-phase-a-w5.json"
    phase_a_csv = build_dir / "positioning-phase-a-w5.csv"
    _run_sidecar(
        session_date=session_date,
        expiry=expiry,
        underlying=underlying,
        wings=ANALYTICAL_WINGS,
        out_json=phase_a_json,
        out_csv=phase_a_csv,
        cache_dir=build_dir / "cache-w5",
    )

    phase_a_session = _load_built(phase_a_json, session_date)
    coverage = required_raw_wings_from_session(phase_a_session)

    final_wings = int(coverage["required_raw_wings"])
    if final_wings > ANALYTICAL_WINGS:
        final_json = build_dir / f"positioning-auto-w{final_wings}.json"
        final_csv = build_dir / f"positioning-auto-w{final_wings}.csv"
        _run_sidecar(
            session_date=session_date,
            expiry=expiry,
            underlying=underlying,
            wings=final_wings,
            out_json=final_json,
            out_csv=final_csv,
            cache_dir=build_dir / f"cache-w{final_wings}",
        )
        phase_b_performed = True
    else:
        final_json = phase_a_json
        final_csv = phase_a_csv
        phase_b_performed = False

    canonical_rows = _load_canonical(Path(canonical_path), session_date)
    final_session = _load_built(final_json, session_date)
    enriched = enrich_session(canonical_rows, final_session, session_date)

    out_dir = Path(enrichment_root) / session_date
    out_dir.mkdir(parents=True, exist_ok=True)
    enriched_json = out_dir / "enriched.json"
    enriched_csv = out_dir / "enriched.csv"
    enriched_json.write_text(json.dumps(enriched, indent=2), encoding="utf-8")
    write_csv(enriched_csv, enriched["rows"])

    # Stable aliases used by UI/API. Preserve phase outputs for auditability.
    stable_json = build_dir / "positioning-auto.json"
    stable_csv = build_dir / "positioning-auto.csv"
    shutil.copy2(final_json, stable_json)
    shutil.copy2(final_csv, stable_csv)

    status_counts = enriched.get("status_counts") or {}
    complete = (
        int(enriched.get("row_count") or 0) == 74
        and int(status_counts.get("AVAILABLE") or 0) == 74
        and int(status_counts.get("SOURCE_MISSING") or 0) == 0
    )

    summary = {
        "model": MODEL,
        "status": "COMPLETE" if complete else "PARTIAL",
        "session_date": session_date,
        "expiry": expiry,
        "underlying": underlying,
        "analytical_wings": ANALYTICAL_WINGS,
        "required_raw_wings": final_wings,
        "raw_strikes_per_checkpoint": final_wings * 2 + 1,
        "phase_b_performed": phase_b_performed,
        "coverage": coverage,
        "source_mode": enriched.get("source_mode"),
        "row_count": enriched.get("row_count"),
        "status_counts": status_counts,
        "fixed_atm": enriched.get("fixed_atm"),
        "positioning_json": str(stable_json),
        "enriched_json": str(enriched_json),
        "enriched_csv": str(enriched_csv),
    }
    (out_dir / "auto-build-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description="Auto dual-basket Historical OI build + enrichment")
    p.add_argument("--session-date", required=True)
    p.add_argument("--expiry", required=True)
    p.add_argument("--underlying", default="NSE_INDEX|Nifty 50")
    p.add_argument("--canonical", default="data/historical-evidence/oi-pattern-library-90d-historical-only-v1.csv")
    args = p.parse_args()

    result = run_auto_enrichment(
        session_date=args.session_date,
        expiry=args.expiry,
        underlying=args.underlying,
        canonical_path=args.canonical,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
