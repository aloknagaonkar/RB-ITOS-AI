#!/usr/bin/env python3
"""Idempotent fail-closed installer. Dry run unless --apply is specified."""
import argparse, hashlib, json, shutil, sys
from datetime import datetime
from pathlib import Path

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--repo',type=Path,required=True)
    ap.add_argument('--apply',action='store_true')
    args=ap.parse_args()
    root=Path(__file__).resolve().parent
    manifest=json.loads((root/'manifest.json').read_text())
    repo=args.repo.expanduser().resolve()
    if not (repo/'backend/market_lab/hilega_milega_strategy_v1.py').is_file():
        sys.exit('INVALID_REPO: expected Hilega strategy source missing')
    ready=[];conflicts=[]
    for rel,info in manifest['files'].items():
        src=root/'payload'/rel
        dst=repo/rel
        if digest(src)!=info['patched_sha256']:
            sys.exit('PACKAGE_INTEGRITY_FAILURE: '+rel)
        if dst.exists() and digest(dst)==info['patched_sha256']:
            print('ALREADY_PATCHED ',rel)
            continue
        if info['mode']=='add':
            if dst.exists():
                conflicts.append(rel)
            else:ready.append(rel)
        elif not dst.is_file() or digest(dst)!=info['expected_before_sha256']:
            conflicts.append(rel)
        else: ready.append(rel)
    if conflicts:
        for rel in conflicts: print('CONFLICT        ',rel)
        sys.exit('REFUSING TO APPLY: no changes written; inspect conflicting files')
    for rel in ready:print('READY           ',rel)
    if not args.apply:
        print(f'DRY_RUN: {len(ready)} files ready; use --apply to install')
        return
    if not ready:
        print('NOTHING_TO_APPLY')
        return
    backup=repo/'.phase7d2-backup'/datetime.now().strftime('%Y%m%dT%H%M%S%f')
    for rel in ready:
        dst=repo/rel
        if dst.exists():
            target=backup/rel
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(dst,target)
    for rel in ready:
        dst=repo/rel
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(root/'payload'/rel,dst)
        print('APPLIED         ',rel)
    print('BACKUP:',backup if any(manifest['files'][x]['mode']=='replace' for x in ready) else 'no existing files replaced')
    print('No services were stopped or restarted. Historical evidence unchanged.')

if __name__=='__main__':main()
