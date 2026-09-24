#!/usr/bin/env python3
from pathlib import Path
import argparse, hashlib, shutil
from datetime import datetime, timezone

TARGETS = {
    "backend/market_lab/hilega_historical_ui_api_v1.py": {
        "before": {"254e954de697db8296ba338578ab26db6f398a3d03b0588ad15edffc6acfc422"},
        "after": "e4fac1faab1766be8b42196c3fc39d9b7034ca58baaa1f23ee87bf23a7fcfc7e",
    },
    "frontend/src/hilegaHistoricalReplay.tsx": {
        "before": {"b21d9e1131cc65382da1e4f88a5140e0360d71f469ba4f2011b63cfc32f2bc58"},
        "after": "6873fa04978de02cf92b67fd6014e4e4a2d47112063acac604b904f24037dabd",
    },
}
TEST = "tests/test_hilega_session_replay_api_v1.py"
TEST_AFTER = "7843bd8681b5c795eeb67ad498eb1e27bc416f915832f2af31363e984184c3da"
DECISION_TABLE = "frontend/src/hilegaDecisionTable.tsx"
DECISION_REQUIRED = "35ff9baf10f0ea223b93964653c960d5588db51ef18d53b408a635ba4cb4e182"

def sha(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser(description="Install Hilega session-centric historical/live integration")
    ap.add_argument("--repo",required=True)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--apply",action="store_true")
    a=ap.parse_args()
    repo=Path(a.repo).resolve()
    payload=Path(__file__).resolve().parent/"files"

    blocked=False
    states={}

    decision=repo/DECISION_TABLE
    if not decision.exists():
        print(f"BLOCKED prerequisite missing: {DECISION_TABLE}")
        raise SystemExit(2)
    dh=sha(decision)
    if dh != DECISION_REQUIRED:
        print(f"BLOCKED prerequisite hash: {DECISION_TABLE} sha256={dh}")
        print("Expected the latest linked CE lifecycle/no-lookahead decision table patch.")
        raise SystemExit(2)
    print(f"PREREQ PASS          {DECISION_TABLE}")

    for rel,spec in TARGETS.items():
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

    tp=repo/TEST
    if tp.exists():
        th=sha(tp)
        if th==TEST_AFTER:
            states[TEST]=("ALREADY_PATCHED",th)
        else:
            states[TEST]=("BLOCKED_EXISTING_TEST",th); blocked=True
    else:
        states[TEST]=("READY_NEW",None)

    print("=== Hilega session-centric/live integration patch ===")
    for rel,(state,h) in states.items():
        print(f"{state:22} {rel}" + (f"  sha256={h}" if h else ""))

    if blocked:
        print("\nBLOCKED: unknown local modification or collision detected.")
        print("Do not force overwrite. Inspect the current source/hash first.")
        raise SystemExit(2)

    if a.check:
        print("\nCHECK PASS: safe known state detected.")
        return

    todo=[rel for rel,(state,_) in states.items() if state in {"READY","READY_NEW"}]
    if not todo:
        print("\nNo changes required; patch is already installed.")
        return

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=repo/".hilega-session-centric-backup"/stamp
    for rel in todo:
        src=repo/rel
        if src.exists():
            dst=backup/rel
            dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(src,dst)

    for rel in todo:
        src=payload/rel
        dst=repo/rel
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dst)

    for rel,spec in TARGETS.items():
        if sha(repo/rel)!=spec["after"]:
            raise SystemExit(f"Post-write hash mismatch: {rel}")
    if sha(repo/TEST)!=TEST_AFTER:
        raise SystemExit(f"Post-write hash mismatch: {TEST}")

    print(f"\nAPPLY PASS: updated {len(todo)} file(s).")
    print(f"Backup: {backup}")
    print("Backend API + frontend only. Strategy rules, live worker and evidence files are unchanged.")

if __name__=="__main__":
    main()
