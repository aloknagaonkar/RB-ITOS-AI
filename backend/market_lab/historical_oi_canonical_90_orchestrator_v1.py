from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .historical_oi_cache_reuse_rate_limit_v1 import run_cache_reuse_enrichment

MODEL = "HISTORICAL_OI_CANONICAL_90_ORCHESTRATOR_V1"
DEFAULT_CANONICAL = Path("data/historical-evidence/oi-pattern-library-90d-historical-only-v1.csv")
DEFAULT_REPORT = Path("data/historical-evidence/historical-oi-enrichment/canonical-90-coverage-v1.json")
BUILD_ROOT = Path("data/historical-evidence/historical-oi-build")


def canonical_dates(path: str | Path = DEFAULT_CANONICAL) -> list[str]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Canonical file not found: {p}")
    values = []
    seen = set()
    with p.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            d = str(row.get("session_date") or "").strip()
            if d and d not in seen:
                seen.add(d)
                values.append(d)
    if not values:
        raise ValueError("Canonical file contains no session_date values")
    return sorted(values)


def _valid_oi_row(row: dict[str, Any]) -> bool:
    return all(
        row.get(k) not in (None, "")
        for k in ("ce_instrument_key","pe_instrument_key","ce_open_interest","pe_open_interest")
    )


def _extract_session_docs(doc: Any) -> list[dict[str, Any]]:
    if not isinstance(doc, dict):
        return []
    if isinstance(doc.get("sessions"), list):
        return [x for x in doc["sessions"] if isinstance(x, dict)]
    if doc.get("session_date"):
        return [doc]
    return []


def _quality_ok(session: dict[str, Any]) -> bool:
    if str(session.get("status") or "") != "AVAILABLE":
        return False
    rows = session.get("rows") or []
    if not isinstance(rows, list) or not rows:
        return False
    return any(isinstance(r, dict) and _valid_oi_row(r) for r in rows)


def _candidate_from_json(path: Path, session_date: str) -> list[dict[str, Any]]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for s in _extract_session_docs(doc):
        if str(s.get("session_date")) != session_date:
            continue
        expiry = str(s.get("expiry") or "").strip()
        if not expiry or not _quality_ok(s):
            continue
        out.append({
            "session_date": session_date,
            "expiry": expiry,
            "source": str(path),
            "wings": s.get("wings"),
            "row_count": s.get("row_count") or len(s.get("rows") or []),
        })
    return out


def _filename_expiry(path: Path, session_date: str) -> str | None:
    # Supports cache names like:
    # NSE_INDEX_Nifty_50__2026-05-20__2026-05-26__w5.json
    m = re.search(
        rf"__{re.escape(session_date)}__(\d{{4}}-\d{{2}}-\d{{2}})__w\d+\.json$",
        path.name,
    )
    return m.group(1) if m else None


def resolve_exact_expiry(
    session_date: str,
    *,
    build_root: str | Path = BUILD_ROOT,
    data_root: str | Path = "data",
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []

    # Priority 1: dedicated Historical OI build directory.
    d = Path(build_root) / session_date
    if d.exists():
        preferred = [
            d / "positioning-auto.json",
            d / "positioning.json",
        ]
        preferred += sorted(d.glob("positioning-auto-w*.json"), reverse=True)
        preferred += sorted(d.glob("positioning-phase-a-w*.json"), reverse=True)
        for p in preferred:
            if p.exists():
                candidates.extend(_candidate_from_json(p, session_date))

    # Priority 2: known positioning caches. Filename embeds both exact
    # session date and expiry; JSON content must independently pass quality.
    root = Path(data_root)
    if root.exists():
        for p in root.glob("historical-positioning-cache*/**/*.json"):
            exp = _filename_expiry(p, session_date)
            if not exp:
                continue
            rows = _candidate_from_json(p, session_date)
            for x in rows:
                if x["expiry"] == exp:
                    candidates.append(x)

    # Deduplicate exact same source/expiry.
    uniq = {}
    for c in candidates:
        uniq[(c["expiry"], c["source"])] = c
    candidates = list(uniq.values())

    expiries = sorted({c["expiry"] for c in candidates})
    if not expiries:
        return {
            "status": "EXPIRY_REQUIRED",
            "session_date": session_date,
            "expiry": None,
            "candidates": [],
        }
    if len(expiries) > 1:
        return {
            "status": "EXPIRY_AMBIGUOUS",
            "session_date": session_date,
            "expiry": None,
            "candidate_expiries": expiries,
            "candidates": candidates,
        }

    # Prefer a dedicated build source for provenance when possible.
    chosen = sorted(
        candidates,
        key=lambda c: (
            0 if "/historical-oi-build/" in c["source"] else 1,
            -int(c.get("wings") or 0),
            c["source"],
        ),
    )[0]
    return {
        "status": "RESOLVED",
        "session_date": session_date,
        "expiry": expiries[0],
        "source": chosen["source"],
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def _existing_complete(session_date: str) -> dict[str, Any] | None:
    p = Path("data/historical-evidence/historical-oi-enrichment") / session_date / "auto-build-summary.json"
    if not p.exists():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    counts = doc.get("status_counts") or {}
    if (
        doc.get("status") == "COMPLETE"
        and int(doc.get("row_count") or 0) == 74
        and int(counts.get("AVAILABLE") or 0) == 74
        and int(counts.get("SOURCE_MISSING") or 0) == 0
    ):
        return doc
    return None


def run_orchestrator(
    *,
    canonical_path: str | Path = DEFAULT_CANONICAL,
    report_path: str | Path = DEFAULT_REPORT,
    only_dates: set[str] | None = None,
    execute: bool = False,
    skip_existing_complete: bool = True,
) -> dict[str, Any]:
    dates = canonical_dates(canonical_path)
    if only_dates:
        dates = [d for d in dates if d in only_dates]

    results = []

    for d in dates:
        existing = _existing_complete(d) if skip_existing_complete else None
        if existing:
            results.append({
                "session_date": d,
                "status": "SKIPPED_COMPLETE",
                "expiry": existing.get("expiry"),
                "required_raw_wings": existing.get("required_raw_wings"),
                "available": 74,
            })
            continue

        resolved = resolve_exact_expiry(d)
        if resolved["status"] != "RESOLVED":
            results.append({
                "session_date": d,
                "status": resolved["status"],
                "expiry": None,
                "candidate_expiries": resolved.get("candidate_expiries"),
            })
            continue

        if not execute:
            results.append({
                "session_date": d,
                "status": "READY",
                "expiry": resolved["expiry"],
                "expiry_source": resolved["source"],
            })
            continue

        try:
            built = run_cache_reuse_enrichment(
                session_date=d,
                expiry=resolved["expiry"],
                canonical_path=canonical_path,
            )
            counts = built.get("status_counts") or {}
            results.append({
                "session_date": d,
                "status": built.get("status"),
                "expiry": resolved["expiry"],
                "expiry_source": resolved["source"],
                "required_raw_wings": built.get("required_raw_wings"),
                "available": counts.get("AVAILABLE", 0),
                "source_missing": counts.get("SOURCE_MISSING", 0),
            })
        except Exception as exc:
            msg = str(exc)
            low = msg.lower()
            if any(x in low for x in ("unavailable","denied","entitlement","not found","no contracts","gateway")):
                status = "PROVIDER_UNAVAILABLE"
            else:
                status = "FAILED"
            results.append({
                "session_date": d,
                "status": status,
                "expiry": resolved["expiry"],
                "expiry_source": resolved["source"],
                "error": msg,
            })

    counts = Counter(r["status"] for r in results)
    report = {
        "model": MODEL,
        "canonical_session_count": len(canonical_dates(canonical_path)),
        "selected_session_count": len(dates),
        "execution_requested": execute,
        "status_counts": dict(sorted(counts.items())),
        "results": results,
    }

    out = Path(report_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    p = argparse.ArgumentParser(description="Resolve and optionally enrich the canonical 90 Historical OI sessions")
    p.add_argument("--canonical", default=str(DEFAULT_CANONICAL))
    p.add_argument("--report", default=str(DEFAULT_REPORT))
    p.add_argument("--date", action="append", dest="dates")
    p.add_argument("--execute", action="store_true",
                   help="Actually download/build/enrich RESOLVED dates. Without this flag the command is dry-run only.")
    p.add_argument("--include-existing-complete", action="store_true")
    args = p.parse_args()

    report = run_orchestrator(
        canonical_path=args.canonical,
        report_path=args.report,
        only_dates=set(args.dates) if args.dates else None,
        execute=args.execute,
        skip_existing_complete=not args.include_existing_complete,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
