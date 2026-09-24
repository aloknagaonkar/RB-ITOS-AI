#!/usr/bin/env python3
from pathlib import Path
import argparse, hashlib, shutil
from datetime import datetime, timezone

REL="tests/test_hilega_decision_table_v1.cjs"
BEFORE="bc3fc1a37c7838a4a78abc2e910fbe64efc8ee8abb8271fe754f2a3201c8d0ba"
AFTER="39353bb452b89850bee5bf6d1cbe42bfbee78468b827d98595780f46e8ffbea2"

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--repo",required=True)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--apply",action="store_true")
    a=ap.parse_args()
    repo=Path(a.repo).resolve()
    dst=repo/REL
    if not dst.exists():
        print("BLOCKED: test file missing"); raise SystemExit(2)
    h=sha(dst)
    if h==AFTER:
        print("ALREADY_PATCHED",REL,h); return
    if h!=BEFORE:
        print("BLOCKED_UNKNOWN_HASH",REL,h); raise SystemExit(2)
    print("READY",REL,h)
    if a.check:
        print("CHECK PASS: fixture-only correction is safe to apply."); return
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=repo/".hilega-test-fixture-backup"/stamp/REL
    backup.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(dst,backup)
    src=Path(__file__).resolve().parent/"files"/REL
    shutil.copy2(src,dst)
    if sha(dst)!=AFTER: raise SystemExit("Post-write hash mismatch")
    print("APPLY PASS: updated test fixture only.")
    print("Production frontend/backend source was not changed.")
    print("Backup:",backup)

if __name__=="__main__":
    main()
