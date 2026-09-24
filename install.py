#!/usr/bin/env python3
from pathlib import Path
import argparse, hashlib, shutil
from datetime import datetime, timezone

FILES = {
  "frontend/src/hilegaDecisionTable.tsx": {
    "before": {"43c668909d8019bf495d01e3d2529a4c4c69770452694e5faf6c3d365b4f8f38","35ff9baf10f0ea223b93964653c960d5588db51ef18d53b408a635ba4cb4e182"},
    "after": "35ff9baf10f0ea223b93964653c960d5588db51ef18d53b408a635ba4cb4e182",
  },
  "tests/test_hilega_decision_table_v1.cjs": {
    "before": {"a0f65ee73c28ab2d659330021425861e3f8af814f3243b5b70cf60f2c68f314a","bc3fc1a37c7838a4a78abc2e910fbe64efc8ee8abb8271fe754f2a3201c8d0ba"},
    "after": "bc3fc1a37c7838a4a78abc2e910fbe64efc8ee8abb8271fe754f2a3201c8d0ba",
  },
  "backend/market_lab/hilega_historical_ui_api_v1.py": {
    "before": {"254e954de697db8296ba338578ab26db6f398a3d03b0588ad15edffc6acfc422","e4fac1faab1766be8b42196c3fc39d9b7034ca58baaa1f23ee87bf23a7fcfc7e"},
    "after": "e4fac1faab1766be8b42196c3fc39d9b7034ca58baaa1f23ee87bf23a7fcfc7e",
  },
  "frontend/src/hilegaHistoricalReplay.tsx": {
    "before": {"b21d9e1131cc65382da1e4f88a5140e0360d71f469ba4f2011b63cfc32f2bc58","6873fa04978de02cf92b67fd6014e4e4a2d47112063acac604b904f24037dabd"},
    "after": "6873fa04978de02cf92b67fd6014e4e4a2d47112063acac604b904f24037dabd",
  },
}
NEW_TEST = "tests/test_hilega_session_replay_api_v1.py"
NEW_TEST_HASH = "7843bd8681b5c795eeb67ad498eb1e27bc416f915832f2af31363e984184c3da"

def sha(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser(description="Cumulative Hilega linked-CE + session-centric integration")
    ap.add_argument("--repo", required=True)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
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
            states[rel]=("ALREADY_TARGET",h)
        elif h in spec["before"]:
            states[rel]=("READY",h)
        else:
            states[rel]=("BLOCKED_UNKNOWN_HASH",h); blocked=True

    tp=repo/NEW_TEST
    if tp.exists():
        h=sha(tp)
        states[NEW_TEST]=("ALREADY_TARGET",h) if h==NEW_TEST_HASH else ("BLOCKED_EXISTING_TEST",h)
        if h!=NEW_TEST_HASH: blocked=True
    else:
        states[NEW_TEST]=("READY_NEW",None)

    print("=== Hilega cumulative session-centric/live integration v2 ===")
    for rel,(state,h) in states.items():
        print(f"{state:22} {rel}" + (f"  sha256={h}" if h else ""))

    if blocked:
        print("\nBLOCKED: an unknown local modification/collision exists.")
        print("Do not force overwrite. Send this output for inspection.")
        raise SystemExit(2)

    if a.check:
        print("\nCHECK PASS: your current 43c668 progressive CE state is supported directly.")
        return

    todo=[rel for rel,(state,_) in states.items() if state in {"READY","READY_NEW"}]
    if not todo:
        print("\nNo changes required; cumulative patch already installed.")
        return

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=repo/".hilega-session-centric-v2-backup"/stamp
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

    for rel,spec in FILES.items():
        if sha(repo/rel)!=spec["after"]:
            raise SystemExit(f"Post-write hash mismatch: {rel}")
    if sha(repo/NEW_TEST)!=NEW_TEST_HASH:
        raise SystemExit(f"Post-write hash mismatch: {NEW_TEST}")

    print(f"\nAPPLY PASS: updated {len(todo)} file(s).")
    print(f"Backup: {backup}")
    print("This cumulative patch includes the linked CE lifecycle fix and the session-centric/live integration.")

if __name__=="__main__":
    main()
