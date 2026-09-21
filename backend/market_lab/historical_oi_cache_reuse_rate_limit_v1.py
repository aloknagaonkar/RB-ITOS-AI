from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .historical_oi_enrichment_v1 import _load_canonical, enrich_session, write_csv
from .historical_oi_auto_enrichment_v1 import required_raw_wings_from_session

MODEL = "HISTORICAL_OI_CACHE_REUSE_RATE_LIMIT_V1"
ANALYTICAL_WINGS = 5


def _load_session_compatible(path: Path, session_date: str) -> dict[str, Any]:
    # Accept newer build-wrapper JSON and older single-session cache JSON.
    doc = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(doc, dict) and isinstance(doc.get("sessions"), list):
        matches = [
            s for s in doc["sessions"]
            if isinstance(s, dict) and str(s.get("session_date")) == session_date
        ]
    elif isinstance(doc, dict) and str(doc.get("session_date")) == session_date:
        matches = [doc]
    else:
        matches = []

    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one compatible session for {session_date}, found {len(matches)}"
        )

    session = matches[0]
    if str(session.get("status")) != "AVAILABLE":
        raise ValueError(
            f"Compatible session is not AVAILABLE for {session_date}: {session.get('status')}"
        )
    if not isinstance(session.get("rows"), list) or not session["rows"]:
        raise ValueError(f"Compatible session has no rows for {session_date}")

    return session


def _session_from_file(path: Path, session_date: str, expiry: str) -> dict[str, Any] | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    sessions = doc.get("sessions") if isinstance(doc, dict) else None
    if not isinstance(sessions, list):
        sessions = [doc] if isinstance(doc, dict) and doc.get("session_date") else []

    for s in sessions:
        if (
            str(s.get("session_date")) == session_date
            and str(s.get("expiry")) == expiry
            and str(s.get("status")) == "AVAILABLE"
            and isinstance(s.get("rows"), list)
            and s.get("rows")
        ):
            return s
    return None


def find_verified_existing_source(
    session_date: str,
    expiry: str,
    *,
    min_wings: int,
    repo_root: str | Path = ".",
) -> Path | None:
    root = Path(repo_root)
    candidates: list[tuple[int, int, Path]] = []

    patterns = [
        f"data/historical-evidence/historical-oi-build/{session_date}/*.json",
        f"data/historical-positioning-cache*/**/*__{session_date}__{expiry}__w*.json",
    ]
    seen: set[Path] = set()

    for pattern in patterns:
        for p in root.glob(pattern):
            if p in seen or not p.is_file():
                continue
            seen.add(p)
            s = _session_from_file(p, session_date, expiry)
            if not s:
                continue
            wings = int(s.get("wings") or 0)
            if wings < min_wings:
                continue
            rows = s.get("rows") or []
            # Reject AVAILABLE shells: require at least one actual CE/PE OI pair.
            has_oi = any(
                r.get("ce_open_interest") is not None
                and r.get("pe_open_interest") is not None
                and r.get("ce_instrument_key")
                and r.get("pe_instrument_key")
                for r in rows if isinstance(r, dict)
            )
            if not has_oi:
                continue
            # Prefer the narrowest adequate source; build-dir artifacts before legacy cache
            source_priority = 0 if "/historical-oi-build/" in str(p) else 1
            candidates.append((wings, source_priority, p))

    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1], str(x[2])))
    return candidates[0][2]


def _manifest(path: Path, session_date: str, expiry: str) -> None:
    path.write_text(
        json.dumps({"sessions":[{"session_date":session_date,"expiry":expiry}]}, indent=2),
        encoding="utf-8",
    )


def _run_sidecar_with_retry(
    *,
    session_date: str,
    expiry: str,
    underlying: str,
    wings: int,
    out_json: Path,
    out_csv: Path,
    cache_dir: Path,
    attempts: int = 3,
    delays: tuple[int, ...] = (60, 180),
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

    last_issue = None
    for attempt in range(1, attempts + 1):
        subprocess.run(cmd, text=True)
        s = _session_from_file(out_json, session_date, expiry) if out_json.exists() else None
        if s:
            return

        issue = ""
        if out_json.exists():
            try:
                doc = json.loads(out_json.read_text(encoding="utf-8"))
                sessions = doc.get("sessions") or []
                if sessions:
                    issue = " ".join(sessions[0].get("issues") or [])
            except Exception:
                pass
        last_issue = issue or f"sidecar did not produce AVAILABLE data on attempt {attempt}"

        if attempt < attempts:
            delay = delays[min(attempt - 1, len(delays) - 1)]
            print(f"Rate-limit/provider retry {attempt}/{attempts}: sleeping {delay}s; issue={last_issue}", flush=True)
            time.sleep(delay)

    raise RuntimeError(last_issue or "historical positioning unavailable after retries")


def run_cache_reuse_enrichment(
    *,
    session_date: str,
    expiry: str,
    underlying: str = "NSE_INDEX|Nifty 50",
    canonical_path: str | Path = "data/historical-evidence/oi-pattern-library-90d-historical-only-v1.csv",
) -> dict[str, Any]:
    build_dir = Path("data/historical-evidence/historical-oi-build") / session_date
    build_dir.mkdir(parents=True, exist_ok=True)

    # Phase A: reuse verified existing exact-expiry w5+ source before making any provider call.
    phase_a_source = find_verified_existing_source(session_date, expiry, min_wings=ANALYTICAL_WINGS)
    phase_a_reused = phase_a_source is not None

    if phase_a_source is None:
        phase_a_source = build_dir / "positioning-phase-a-w5.json"
        _run_sidecar_with_retry(
            session_date=session_date,
            expiry=expiry,
            underlying=underlying,
            wings=ANALYTICAL_WINGS,
            out_json=phase_a_source,
            out_csv=build_dir / "positioning-phase-a-w5.csv",
            cache_dir=build_dir / "cache-w5",
        )

    phase_a_session = _load_session_compatible(phase_a_source, session_date)
    coverage = required_raw_wings_from_session(phase_a_session)
    required = int(coverage["required_raw_wings"])

    # Phase B: reuse any verified already-existing wider artifact before fetching.
    final_source = find_verified_existing_source(session_date, expiry, min_wings=required)
    phase_b_reused = final_source is not None

    if final_source is None:
        final_source = build_dir / f"positioning-auto-w{required}.json"
        _run_sidecar_with_retry(
            session_date=session_date,
            expiry=expiry,
            underlying=underlying,
            wings=required,
            out_json=final_source,
            out_csv=build_dir / f"positioning-auto-w{required}.csv",
            cache_dir=build_dir / f"cache-w{required}",
        )

    final_session = _load_session_compatible(final_source, session_date)
    canonical_rows = _load_canonical(Path(canonical_path), session_date)
    enriched = enrich_session(canonical_rows, final_session, session_date)

    out_dir = Path("data/historical-evidence/historical-oi-enrichment") / session_date
    out_dir.mkdir(parents=True, exist_ok=True)
    enriched_json = out_dir / "enriched.json"
    enriched_csv = out_dir / "enriched.csv"
    enriched_json.write_text(json.dumps(enriched, indent=2), encoding="utf-8")
    write_csv(enriched_csv, enriched["rows"])

    # Stable alias for UI/other jobs.
    shutil.copy2(final_source, build_dir / "positioning-auto.json")

    counts = enriched.get("status_counts") or {}
    complete = (
        int(enriched.get("row_count") or 0) == 74
        and int(counts.get("AVAILABLE") or 0) == 74
        and int(counts.get("SOURCE_MISSING") or 0) == 0
    )

    summary = {
        "model": MODEL,
        "status": "COMPLETE" if complete else "PARTIAL",
        "session_date": session_date,
        "expiry": expiry,
        "analytical_wings": ANALYTICAL_WINGS,
        "required_raw_wings": required,
        "phase_a_source": str(phase_a_source),
        "phase_a_reused": phase_a_reused,
        "phase_b_source": str(final_source),
        "phase_b_reused": phase_b_reused,
        "row_count": enriched.get("row_count"),
        "status_counts": counts,
        "fixed_atm": enriched.get("fixed_atm"),
    }
    (out_dir / "auto-build-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description="Historical OI enrichment with verified cache reuse and rate-limit retry")
    p.add_argument("--session-date", required=True)
    p.add_argument("--expiry", required=True)
    p.add_argument("--underlying", default="NSE_INDEX|Nifty 50")
    args = p.parse_args()
    print(json.dumps(run_cache_reuse_enrichment(
        session_date=args.session_date,
        expiry=args.expiry,
        underlying=args.underlying,
    ), indent=2))


if __name__ == "__main__":
    main()
