#!/usr/bin/env python3
from __future__ import annotations
import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

FILES = [
    "backend/market_lab/hilega_mtf_alignment_research_v1.py",
    "backend/market_lab/hilega_mtf_alignment_research_cli_v1.py",
    "tests/test_hilega_mtf_alignment_research_v1.py",
]

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    a = p.parse_args()

    repo = Path(a.repo).resolve()
    src_root = Path(__file__).resolve().parent / "files"

    for rel in FILES:
        if not (src_root / rel).is_file():
            raise SystemExit(f"PACKAGE_MISSING:{rel}")

    print("READY")
    print("Research-only MTF-1A: 14-session 5m/10m/15m alignment study")
    print("No live worker, strategy, UI, execution, option or API files are modified.")
    if a.check:
        print("CHECK PASS")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = repo / ".hilega-mtf-alignment-research-v1-backup" / stamp
    for rel in FILES:
        dst = repo / rel
        if dst.exists():
            b = backup / rel
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, b)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_root / rel, dst)

    print("APPLY PASS")
    print("Backup root:", backup)
    print("No service restart required.")

if __name__ == "__main__":
    main()
