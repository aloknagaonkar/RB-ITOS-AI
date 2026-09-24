#!/usr/bin/env python3
from pathlib import Path
import argparse, hashlib, shutil
from datetime import datetime, timezone

FILES = {
    "frontend/src/hilegaDecisionTable.tsx": {
        "before": {"0c7723ffdea196ce9ac63ad032565f6872c770c50a40ec3b8a477c5204537bba"},
        "after": "43c668909d8019bf495d01e3d2529a4c4c69770452694e5faf6c3d365b4f8f38",
    },
    "tests/test_hilega_decision_table_v1.cjs": {
        "before": {"fb52a29007f31be775d1fc2bd5e15e81f0ea7ecb90fa2af75c02906430b81f73"},
        "after": "a0f65ee73c28ab2d659330021425861e3f8af814f3243b5b70cf60f2c68f314a",
    },
}

def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser(description="Install Hilega CE progressive/no-lookahead UI fix")
    ap.add_argument("--repo", required=True)
    mode=ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args=ap.parse_args()
    repo=Path(args.repo).resolve()
    payload=Path(__file__).resolve().parent/"files"

    states={}
    blocked=False
    for rel,spec in FILES.items():
        dst=repo/rel
        if not dst.exists():
            states[rel]=("MISSING",None)
            blocked=True
            continue
        h=sha(dst)
        if h==spec["after"]:
            states[rel]=("ALREADY_PATCHED",h)
        elif h in spec["before"]:
            states[rel]=("READY",h)
        else:
            states[rel]=("BLOCKED_UNKNOWN_HASH",h)
            blocked=True

    print("=== Hilega CE progressive/no-lookahead patch ===")
    for rel,(state,h) in states.items():
        print(f"{state:20} {rel}" + (f"  sha256={h}" if h else ""))

    if blocked:
        print("\nBLOCKED: at least one target is missing or has an unknown local modification.")
        print("Do not force-overwrite it. Inspect the current file first.")
        raise SystemExit(2)

    if args.check:
        if all(s[0]=="ALREADY_PATCHED" for s in states.values()):
            print("\nCHECK PASS: patch is already installed.")
        else:
            print("\nCHECK PASS: exact known predecessor detected; safe to apply.")
        return

    todo=[rel for rel,(state,_) in states.items() if state=="READY"]
    if not todo:
        print("\nNo changes required; patch is already installed.")
        return

    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=repo/".hilega-ce-progressive-backup"/stamp
    for rel in todo:
        src=repo/rel
        b=backup/rel
        b.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,b)

    for rel in todo:
        src=payload/rel
        dst=repo/rel
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dst)
        got=sha(dst)
        expected=FILES[rel]["after"]
        if got!=expected:
            raise SystemExit(f"Hash verification failed after writing {rel}")

    print(f"\nAPPLY PASS: updated {len(todo)} file(s).")
    print(f"Backup: {backup}")
    print("No backend, strategy, API, historical evidence or worker files were changed.")

if __name__=="__main__":
    main()
