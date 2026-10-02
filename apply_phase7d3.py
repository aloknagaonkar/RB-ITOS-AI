#!/usr/bin/env python3
"""Fail-closed, idempotent Phase 7D.3 installer; dry run by default."""
import argparse, hashlib, json, shutil, sys
from datetime import datetime, timezone
from pathlib import Path

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    package=Path(__file__).resolve().parent
    manifest=json.loads((package/'manifest.json').read_text())
    repo=args.repo.expanduser().resolve()
    if not (repo/'backend/market_lab/hilega_milega_strategy_v1.py').is_file():
        sys.exit('INVALID_REPOSITORY: strategy module missing')
    ready=[];conflicts=[]
    for rel,meta in manifest['files'].items():
        src=package/'payload'/rel
        dst=repo/rel
        if not src.is_file() or digest(src)!=meta['patched_sha256']:
            sys.exit('PACKAGE_INTEGRITY_FAILURE:'+rel)
        if dst.is_file() and digest(dst)==meta['patched_sha256']:
            print('ALREADY_PATCHED',rel)
        elif meta['mode']=='add':
            if dst.exists():conflicts.append(rel)
            else:ready.append(rel)
        elif dst.is_file() and digest(dst)==meta['expected_before_sha256']:
            ready.append(rel)
        else:conflicts.append(rel)
    if conflicts:
        for rel in conflicts:print('CONFLICT',rel)
        sys.exit('NO CHANGES APPLIED: newer/different VM code detected; do not force overwrite')
    for rel in ready:print('READY',rel)
    if not args.apply:
        print('DRY_RUN:',len(ready),'files ready. Pass --apply to install.')
        return
    backup=repo/'.phase7d3-backup'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    for rel in ready:
        dst=repo/rel
        if dst.exists():
            target=backup/rel
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(dst,target)
    for rel in ready:
        dst=repo/rel
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(package/'payload'/rel,dst)
        print('APPLIED',rel)
    print('BACKUP:',backup if any(manifest['files'][x]['mode']=='replace' for x in ready) else 'none needed')
    print('No services restarted; capture is opt-in and off by default.')

if __name__=='__main__': main()
