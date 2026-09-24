#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, shutil
from datetime import datetime, timezone
from pathlib import Path

EXPECTED = {
    'frontend/src/hilegaDecisionTable.tsx': '0fd1b71c4d7754fd45c0b34f2b5c3529f28baaedb733f9e28e8a8927f53bd8e3',
    'tests/test_hilega_decision_table_v1.cjs': 'c941eae008649e126b05b03d2f1406668663a4dfd35b63a51a941b8822131bc4',
}

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--repo', required=True, type=Path)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--check', action='store_true')
    g.add_argument('--apply', action='store_true')
    args=ap.parse_args()
    repo=args.repo.resolve()
    here=Path(__file__).resolve().parent
    srcroot=here/'files'
    problems=[]
    for rel, expected in EXPECTED.items():
        target=repo/rel
        if not target.exists():
            problems.append(f'MISSING: {rel}')
            continue
        actual=sha(target)
        newhash=sha(srcroot/rel)
        if actual==newhash:
            print(f'ALREADY PATCHED: {rel}')
        elif actual==expected:
            print(f'COMPATIBLE: {rel}')
        else:
            problems.append(f'BLOCKED: {rel} differs from expected current-checkpoint classifier version ({actual})')
    if problems:
        print('\n'.join(problems))
        print('No files modified. Do not force overwrite; inspect current source first.')
        return 2
    if args.check:
        print('CHECK PASSED. No files modified.')
        return 0
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=repo/'.hilega-rule-nifty-delta-backup'/stamp
    changed=0
    for rel in EXPECTED:
        target=repo/rel; source=srcroot/rel
        if sha(target)==sha(source):
            continue
        out=backup/rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target,out)
        shutil.copy2(source,target)
        print(f'PATCHED: {rel}')
        changed+=1
    if changed:
        print(f'APPLIED. Backup: {backup}')
    else:
        print('ALREADY PATCHED. No changes required.')
    print('Frontend/test only. No backend, strategy, evidence, API, or worker process changed.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
