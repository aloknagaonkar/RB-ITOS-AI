from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .historical_oi_auto_enrichment_v1 import run_auto_enrichment

MODEL = "HISTORICAL_OI_ENRICHMENT_BATCH_V1"


def _session_meta(path: Path, session_date: str) -> dict[str, Any] | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    sessions = doc.get("sessions") or []
    for s in sessions:
        if str(s.get("session_date")) == session_date:
            return s
    return None


def discover_existing_builds(
    build_root: str | Path = "data/historical-evidence/historical-oi-build",
) -> list[dict[str, Any]]:
    root = Path(build_root)
    out: list[dict[str, Any]] = []
    if not root.exists():
        return out

    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        session_date = d.name
        # Prefer stable automatic output, then normal current build, then any auto/phase JSON.
        candidates = [
            d / "positioning-auto.json",
            d / "positioning.json",
        ]
        candidates += sorted(d.glob("positioning-auto-w*.json"), reverse=True)
        candidates += sorted(d.glob("positioning-phase-a-w*.json"), reverse=True)

        chosen = None
        meta = None
        for p in candidates:
            if not p.exists():
                continue
            m = _session_meta(p, session_date)
            if not m:
                continue
            if m.get("status") != "AVAILABLE":
                continue
            if not m.get("expiry"):
                continue
            chosen = p
            meta = m
            break

        if chosen and meta:
            out.append({
                "session_date": session_date,
                "expiry": str(meta["expiry"]),
                "source": str(chosen),
                "wings": meta.get("wings"),
                "row_count": meta.get("row_count"),
            })
    return out


def run_batch(
    *,
    build_root: str | Path = "data/historical-evidence/historical-oi-build",
    only_dates: set[str] | None = None,
    skip_existing_complete: bool = True,
) -> dict[str, Any]:
    discovered = discover_existing_builds(build_root)
    results = []

    for item in discovered:
        d = item["session_date"]
        if only_dates and d not in only_dates:
            continue

        summary_path = Path("data/historical-evidence/historical-oi-enrichment") / d / "auto-build-summary.json"
        if skip_existing_complete and summary_path.exists():
            try:
                old = json.loads(summary_path.read_text(encoding="utf-8"))
                if old.get("status") == "COMPLETE" and (old.get("status_counts") or {}).get("AVAILABLE") == 74:
                    results.append({
                        "session_date": d,
                        "expiry": item["expiry"],
                        "status": "SKIPPED_COMPLETE",
                        "required_raw_wings": old.get("required_raw_wings"),
                        "available": 74,
                    })
                    continue
            except Exception:
                pass

        try:
            result = run_auto_enrichment(
                session_date=d,
                expiry=item["expiry"],
            )
            results.append({
                "session_date": d,
                "expiry": item["expiry"],
                "status": result.get("status"),
                "required_raw_wings": result.get("required_raw_wings"),
                "available": (result.get("status_counts") or {}).get("AVAILABLE", 0),
                "source_missing": (result.get("status_counts") or {}).get("SOURCE_MISSING", 0),
            })
        except Exception as exc:
            results.append({
                "session_date": d,
                "expiry": item["expiry"],
                "status": "FAILED",
                "error": str(exc),
            })

    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    return {
        "model": MODEL,
        "discovered_build_count": len(discovered),
        "processed_count": len(results),
        "status_counts": counts,
        "results": results,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Batch auto-enrich existing Historical OI builds")
    p.add_argument("--date", action="append", dest="dates")
    p.add_argument("--include-existing-complete", action="store_true")
    args = p.parse_args()

    result = run_batch(
        only_dates=set(args.dates) if args.dates else None,
        skip_existing_complete=not args.include_existing_complete,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
