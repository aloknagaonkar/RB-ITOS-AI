#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, shutil, sys
from datetime import datetime, timezone
from pathlib import Path
EXPECTED={'frontend/src/hilegaDecisionTable.tsx': '486c19c2d68aad78fad0d3ec7c8b31dc8dbbc78d3ae673aac88c8cf33911c95f', 'frontend/src/hilegaDecisionTable.css': '4ead8bbeeb5586d4d7299d7590e38659143952218fcc41f05231950ea150f6f1', 'tests/test_hilega_decision_table_v1.cjs': '05d96f8807cce976351326f07c737127a34b051aaf8793a5e10c32ee4e55d8fd'}
FILES=['frontend/src/hilegaDecisionTable.tsx', 'frontend/src/hilegaDecisionTable.css', 'tests/test_hilega_decision_table_v1.cjs']
def main():
 p=argparse.ArgumentParser();p.add_argument('--repo',required=True,type=Path)
 g=p.add_mutually_exclusive_group(required=True);g.add_argument('--check',action='store_true');g.add_argument('--apply',action='store_true')
 a=p.parse_args();repo=a.repo.expanduser().resolve();base=Path(__file__).resolve().parent/'files'
 problems=[];changes=[]
 for rel in FILES:
  dst=repo/rel;src=base/rel
  if not dst.is_file():problems.append(f'Missing target: {rel}');continue
  if not src.is_file():problems.append(f'Missing patch file: {rel}');continue
  current=hashlib.sha256(dst.read_bytes()).hexdigest()
  target=hashlib.sha256(src.read_bytes()).hexdigest()
  if current==target:continue
  if current!=EXPECTED[rel]:problems.append(f'Unexpected current version: {rel} ({current})');continue
  changes.append(rel)
 if problems:
  print('\n'.join('BLOCKED: '+x for x in problems));sys.exit(2)
 print('\n'.join('PATCH: '+x for x in changes) or 'ALREADY INSTALLED: no changes needed')
 if a.check:print('CHECK PASSED; no files changed.');return
 if not changes:return
 backup=repo/'.hilega-lifecycle-consistency-backup'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
 for rel in changes:
  src=base/rel;dst=repo/rel;b=backup/rel;b.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dst,b);shutil.copy2(src,dst)
 print('APPLIED. Backups:',backup)
 print('Frontend-only lifecycle display fix. Strategy/backend/live services/evidence unchanged.')
if __name__=='__main__':main()
