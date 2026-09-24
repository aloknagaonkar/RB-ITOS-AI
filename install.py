#!/usr/bin/env python3
from pathlib import Path
import argparse, hashlib, shutil
from datetime import datetime, timezone

FILES = {
  "frontend/src/hilegaDecisionTable.tsx": {
    "before": {"43c668909d8019bf495d01e3d2529a4c4c69770452694e5faf6c3d365b4f8f38"},
    "after": "35ff9baf10f0ea223b93964653c960d5588db51ef18d53b408a635ba4cb4e182"
  },
  "tests/test_hilega_decision_table_v1.cjs": {
    "before": {"a0f65ee73c28ab2d659330021425861e3f8af814f3243b5b70cf60f2c68f314a"},
    "after": "bc3fc1a37c7838a4a78abc2e910fbe64efc8ee8abb8271fe754f2a3201c8d0ba"
  }
}

def sha(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--repo",required=True)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--apply",action="store_true")
    a=ap.parse_args()
    repo=Path(a.repo).resolve()
    payload=Path(__file__).resolve().parent/"files"

    states={}
    blocked=False
    for rel,spec in FILES.items():
        p=repo/rel
        if not p.exists():
            states[rel]=("MISSING",None); blocked=True; continue
        h=sha(p)
        if h==spec["after"]:
            states[rel]=("ALREADY_PATCHED",h)
        elif h in spec["before"]:
            states[rel]=("READY",h)
        else:
            states[rel]=("BLOCKED_UNKNOWN_HASH",h); blocked=True

    print("=== Hilega linked CE lifecycle patch ===")
    for rel,(state,h) in states.items():
        print(f"{state:20} {rel}" + (f"  sha256={h}" if h else ""))

    if blocked:
        print("\nBLOCKED: current source does not match the exact known predecessor.")
        print("Do not force overwrite; inspect the current file first.")
        raise SystemExit(2)

    if a.check:
        print("\nCHECK PASS: safe state detected.")
        return

    todo=[rel for rel,(state,_) in states.items() if state=="READY"]
    if not todo:
        print("\nNo changes required; patch already installed.")
        return

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=repo/".hilega-ce-linked-lifecycle-backup"/stamp
    for rel in todo:
        src=repo/rel
        dst=backup/rel
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dst)

    for rel in todo:
        src=payload/rel
        dst=repo/rel
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dst)
        if sha(dst)!=FILES[rel]["after"]:
            raise SystemExit(f"Post-write hash verification failed: {rel}")

    print(f"\nAPPLY PASS: updated {len(todo)} file(s)")
    print(f"Backup: {backup}")
    print("Frontend/test only. No backend, strategy, API or worker files changed.")

if __name__=="__main__":
    main()
