#!/usr/bin/env python3
"""Additive Hilega replay UI integration. --check first, then --apply.

Copies only new files and makes two narrow additions to existing source. Does NOT
restart services, run migrations, overwrite historical evidence or access credentials.
"""
import argparse
from pathlib import Path
import shutil
from datetime import datetime, timezone

FILES = [
 'backend/market_lab/hilega_historical_ui_api_v1.py',
 'frontend/src/hilegaHistoricalReplay.tsx',
 'frontend/src/hilegaHistoricalReplay.css',
 'tests/test_hilega_historical_ui_api_v1.py',
]
REPLACEMENTS = {
 'backend/market_lab/api.py': [
  ('from .historical_replay_ui_api_v1 import router as historical_replay_router',
   'from .historical_replay_ui_api_v1 import router as historical_replay_router\nfrom .hilega_historical_ui_api_v1 import router as hilega_historical_router'),
  ('    app.include_router(historical_replay_router)',
   '    app.include_router(historical_replay_router)\n    app.include_router(hilega_historical_router)'),
 ],
 'frontend/src/historicalReplay.tsx': [
  ("import HistoricalReplayOperations from './historicalReplayOperations'",
   "import HistoricalReplayOperations from './historicalReplayOperations'\nimport HilegaHistoricalReplay from './hilegaHistoricalReplay'"),
  ('    <HistoricalReplayOperations\n', '    <HilegaHistoricalReplay selectedDate={selected} />\n\n    <HistoricalReplayOperations\n'),
 ],
}

def main():
 p=argparse.ArgumentParser()
 p.add_argument('--repo',type=Path,required=True)
 g=p.add_mutually_exclusive_group(required=True)
 g.add_argument('--check',action='store_true')
 g.add_argument('--apply',action='store_true')
 a=p.parse_args()
 repo=a.repo.expanduser().resolve()
 patch=Path(__file__).resolve().parent
 issues=[]; planned=[]
 for rel in FILES:
  dest=repo/rel
  src=patch/rel
  if not src.is_file():issues.append(f'Missing patch file: {rel}')
  elif dest.exists():
   if dest.read_bytes()==src.read_bytes():planned.append(f'ALREADY PRESENT: {rel}')
   else:issues.append(f'Existing file differs; manual merge needed: {rel}')
  else:planned.append(f'ADD: {rel}')
 for rel,rules in REPLACEMENTS.items():
  path=repo/rel
  if not path.is_file():issues.append(f'Missing target: {rel}');continue
  content=path.read_text()
  for old,new in rules:
   if new in content:planned.append(f'ALREADY INTEGRATED: {rel}');continue
   if content.count(old)!=1:issues.append(f'Cannot safely locate unique insertion in {rel}: {old!r}')
   else:content=content.replace(old,new,1);planned.append(f'PATCH: {rel}')
 if issues:
  print('\n'.join('BLOCKED: '+x for x in issues))
  raise SystemExit(2)
 print('\n'.join(planned))
 if a.check:print('CHECK PASSED; no files modified.');return
 backup=repo/'.hilega-ui-integration-backup'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 backup.mkdir(parents=True)
 for rel in REPLACEMENTS:
  target=repo/rel;dest=backup/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,dest)
 for rel in FILES:
  dest=repo/rel
  if not dest.exists():dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(patch/rel,dest)
 for rel,rules in REPLACEMENTS.items():
  path=repo/rel;content=path.read_text()
  for old,new in rules:
   if new not in content:content=content.replace(old,new,1)
  path.write_text(content)
 print(f'APPLIED. Original integration targets backed up: {backup}')
 print('No running processes or historical evidence were changed.')

if __name__=='__main__':main()
