#!/usr/bin/env python3
import hashlib,json,shutil,sys
from pathlib import Path
from zipfile import ZipFile
root=Path.cwd().resolve()
archive=Path(__file__).resolve().with_name('midpoint_live_ui_performance_fix.zip')
if not (root/'backend/market_lab/api.py').is_file(): raise SystemExit('Run from RB-ITOS-AI root')
with ZipFile(archive) as z:
  manifest=json.loads(z.read('manifest.json'))
  planned=[]
  for rel,expected in manifest.items():
    target=root/rel; desired=z.read('files/'+rel)
    current=hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
    if current==hashlib.sha256(desired).hexdigest(): continue
    if current!=expected: raise SystemExit('STOP: source differs from reviewed ZIP: '+rel)
    if target.with_name(target.name+'.pre-live-ui-perf.bak').exists(): raise SystemExit('STOP: backup exists: '+rel)
    planned.append((target,desired))
  for target,desired in planned:
    shutil.copy2(target,target.with_name(target.name+'.pre-live-ui-perf.bak'))
    target.write_bytes(desired)
  print('Applied',len(planned),'files. No process restarted.')
