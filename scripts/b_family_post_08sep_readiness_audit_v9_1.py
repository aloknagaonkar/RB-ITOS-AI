#!/usr/bin/env python3
"""
B FAMILY — POST-08-SEP UNSEEN VALIDATION READINESS AUDIT V9.1

Purpose
-------
Before touching the frozen 45-event research sample again, discover exactly
which post-2026-09-08 artifacts already exist in the repository.

This script does NOT reconstruct B, does NOT change strategy logic, and does
NOT tune any thresholds.

It scans for:
- underlying 1m OHLC coverage after 2026-09-08
- NIFTY futures / VWAP coverage after 2026-09-08
- midpoint framework events after 2026-09-08
- evidence / positioning artifacts
- existing scripts capable of generating those artifacts

The output tells us whether we can immediately run unseen B validation or
which single data-generation step is still missing.
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

CUTOFF = "2026-09-08"
ROOTS = [Path("data"), Path(".data")]
SCRIPT_ROOT = Path("scripts")
BACKEND_ROOT = Path("backend")

MAX_FILE_BYTES = 80 * 1024 * 1024
TEXT_SUFFIXES = {".csv", ".json", ".jsonl"}


def date_from_text(v):
    if not isinstance(v, str):
        return None
    m = re.search(r"(20\d\d-\d\d-\d\d)", v)
    return m.group(1) if m else None


def post(d):
    return bool(d and d > CUTOFF)


def csv_profile(path):
    out = {
        "path": str(path),
        "kind": "CSV",
        "header": [],
        "post_dates": set(),
        "rows_post": 0,
        "error": None,
    }
    try:
        with path.open(newline="", errors="replace") as f:
            r = csv.DictReader(f)
            out["header"] = r.fieldnames or []
            for row in r:
                d = None
                for k in (
                    "session_date", "date", "timestamp", "datetime",
                    "time", "ts", "candle_timestamp", "event_time"
                ):
                    if k in row:
                        d = date_from_text(row.get(k))
                        if d:
                            break
                if post(d):
                    out["post_dates"].add(d)
                    out["rows_post"] += 1
    except Exception as e:
        out["error"] = repr(e)
    return out


def walk_dates(obj, dates):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in {
                "session_date", "date", "timestamp", "datetime",
                "time", "ts", "candle_timestamp", "event_time"
            }:
                d = date_from_text(v)
                if post(d):
                    dates.add(d)
            walk_dates(v, dates)
    elif isinstance(obj, list):
        for v in obj:
            walk_dates(v, dates)


def json_profile(path):
    out = {
        "path": str(path),
        "kind": path.suffix.upper().lstrip("."),
        "header": [],
        "post_dates": set(),
        "rows_post": None,
        "error": None,
    }
    try:
        if path.suffix == ".json":
            obj = json.loads(path.read_text(errors="replace"))
            walk_dates(obj, out["post_dates"])
        else:
            dates = set()
            n = 0
            with path.open(errors="replace") as f:
                for line in f:
                    if CUTOFF[:4] not in line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    before = len(dates)
                    walk_dates(obj, dates)
                    if len(dates) > before:
                        n += 1
            out["post_dates"] = dates
            out["rows_post"] = n
    except Exception as e:
        out["error"] = repr(e)
    return out


def classify(p):
    name = Path(p["path"]).name.lower()
    hdr = {x.lower() for x in p.get("header", [])}

    tags = []
    if {"open", "high", "low", "close"}.issubset(hdr):
        tags.append("OHLC")
    if "vwap" in hdr or "vwap" in name:
        tags.append("VWAP")
    if "future" in name or "fut" in name:
        tags.append("FUTURES_NAME")
    if "underlying" in name or "nifty" in name:
        tags.append("UNDERLYING_OR_NIFTY_NAME")
    if "framework" in name and "midpoint" in name:
        tags.append("MIDPOINT_FRAMEWORK")
    if "evidence" in name:
        tags.append("EVIDENCE")
    if "positioning" in name:
        tags.append("POSITIONING")
    if "option" in name:
        tags.append("OPTION")
    return tags


def scan_data():
    profiles = []
    seen = set()

    for root in ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                rp = path.resolve()
            except Exception:
                rp = path
            if rp in seen:
                continue
            seen.add(rp)

            try:
                size = path.stat().st_size
            except Exception:
                continue
            if size > MAX_FILE_BYTES:
                continue

            if path.suffix.lower() == ".csv":
                p = csv_profile(path)
            else:
                p = json_profile(path)

            if p["post_dates"]:
                p["tags"] = classify(p)
                profiles.append(p)

    return profiles


def scan_scripts():
    hits = []
    needles = (
        "opening_candle_midpoint_framework_v1",
        "midpoint-v2-nifty-futures-vwap",
        "historical_underlying",
        "underlying-ohlc",
        "futures_vwap",
        "Candidate A",
        "family_b_for_event",
    )

    for root in (SCRIPT_ROOT, BACKEND_ROOT):
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            try:
                txt = path.read_text(errors="replace")
            except Exception:
                continue
            matched = [n for n in needles if n.lower() in txt.lower()]
            if matched:
                hits.append((str(path), matched))
    return hits


def fmt_dates(ds):
    ds = sorted(ds)
    if not ds:
        return "-"
    if len(ds) <= 12:
        return ", ".join(ds)
    return f"{ds[0]} .. {ds[-1]} ({len(ds)} days)"


def main():
    profiles = scan_data()
    scripts = scan_scripts()

    print("B FAMILY — POST-08-SEP UNSEEN VALIDATION READINESS AUDIT V9.1")
    print("=" * 118)
    print("Cutoff (research sample ends):", CUTOFF)
    print("Post-cutoff data artifacts found:", len(profiles))
    print()

    buckets = defaultdict(list)
    for p in profiles:
        tags = p.get("tags", [])
        if "MIDPOINT_FRAMEWORK" in tags:
            buckets["FRAMEWORK"].append(p)
        if "OHLC" in tags:
            buckets["OHLC"].append(p)
        if "VWAP" in tags or "FUTURES_NAME" in tags:
            buckets["FUTURES_VWAP"].append(p)
        if "EVIDENCE" in tags:
            buckets["EVIDENCE"].append(p)
        if "POSITIONING" in tags:
            buckets["POSITIONING"].append(p)

    for name in ("FRAMEWORK", "OHLC", "FUTURES_VWAP", "EVIDENCE", "POSITIONING"):
        print(name)
        print("-" * 118)
        rows = buckets[name]
        if not rows:
            print("NONE")
        else:
            for p in sorted(rows, key=lambda x: x["path"]):
                print(p["path"])
                print("  tags      :", ",".join(p.get("tags", [])) or "-")
                print("  post dates:", fmt_dates(p["post_dates"]))
                if p.get("header"):
                    print("  header    :", ",".join(p["header"][:30]))
                if p.get("error"):
                    print("  error     :", p["error"])
        print()

    all_post = sorted({d for p in profiles for d in p["post_dates"]})
    print("ALL POST-CUTOFF DATES DISCOVERED")
    print("-" * 118)
    print(fmt_dates(all_post))
    print()

    print("RELEVANT GENERATOR / VALIDATION SCRIPTS")
    print("-" * 118)
    for path, matched in sorted(scripts):
        print(path)
        print("  matches:", ", ".join(matched))
    print()

    framework_days = {d for p in buckets["FRAMEWORK"] for d in p["post_dates"]}
    ohlc_days = {d for p in buckets["OHLC"] for d in p["post_dates"]}
    fv_days = {d for p in buckets["FUTURES_VWAP"] for d in p["post_dates"]}

    common = sorted(framework_days & ohlc_days & fv_days)

    print("READINESS")
    print("=" * 118)
    print("post framework days :", len(framework_days), fmt_dates(framework_days))
    print("post OHLC days      :", len(ohlc_days), fmt_dates(ohlc_days))
    print("post futures/VWAP   :", len(fv_days), fmt_dates(fv_days))
    print("3-way common days   :", len(common), fmt_dates(common))

    if common:
        print()
        print("STATUS: READY_OR_NEAR_READY")
        print("There are post-cutoff days with framework + OHLC + futures/VWAP artifacts.")
        print("Next: wire ONLY these untouched dates into canonical family_b_for_event() and V8.2.")
    else:
        print()
        print("STATUS: NOT_YET_WIRED")
        if not framework_days:
            print("MISSING: post-cutoff midpoint framework artifact.")
        if not ohlc_days:
            print("MISSING: post-cutoff underlying OHLC artifact.")
        if not fv_days:
            print("MISSING: post-cutoff futures/VWAP artifact.")
        print("Do not reconstruct B by hand. Use the frozen generators identified above.")

    print()
    print("IMPORTANT")
    print("- This is discovery/readiness only.")
    print("- No frozen B logic or risk parameter is changed.")
    print("- No post-08-Sep result is folded back into the 45-event research sample.")
    print("- observation_only / execution settings are untouched.")


if __name__ == "__main__":
    main()
