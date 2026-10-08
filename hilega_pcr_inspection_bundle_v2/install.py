"""Source/UI installer only. Does not arm, restart or call broker APIs."""
from pathlib import Path
from datetime import datetime,timezone
import json,shutil,subprocess,sys,os
root=Path.cwd();bundle=Path(__file__).resolve().parent;planned={}
for rel,patches in json.loads((bundle/'patches.json').read_text()).items():
 p=root/rel;s=p.read_text()
 for old,new in patches:
  if new in s:continue
  if new.startswith("import ") and new.splitlines()[0] in s:continue
  if s.count(old)!=1:raise SystemExit('STOP: source anchor differs: '+rel+' '+old[:65])
  s=s.replace(old,new,1)
 if rel.endswith('hilegaMilegaShadow.tsx') and '<HilegaPcrWorkspace/>' not in s:
  anchor='    <HilegaExpiryWorkspace/>'
  if s.count(anchor)!=1:raise SystemExit('STOP: expiry workspace anchor differs')
  s="import HilegaPcrWorkspace from './hilegaPcrWorkspace'\n"+s.replace(anchor,anchor+'\n    <HilegaPcrWorkspace/>')
 seen=set();lines=[]
 for line in s.splitlines(keepends=True):
  if line.startswith('import ') and 'hilegaPcr' in line:
   if line in seen:continue
   seen.add(line)
  lines.append(line)
 planned[p]=''.join(lines).encode()
for p in (bundle/'files').rglob('*'):
 if p.is_file():planned[root/p.relative_to(bundle/'files')]=p.read_bytes()
backup=root/'data/backups'/('hilega-pcr-inspection-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));backup.mkdir(parents=True)
existed={p:p.exists() for p in planned}
for p,exists in existed.items():
 if exists:
  target=backup/p.relative_to(root);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
dist=root/'frontend/dist';had_dist=dist.exists()
if had_dist:shutil.copytree(dist,backup/'frontend-dist')
try:
 for p,value in planned.items():p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(value)
 env={**os.environ,'PYTHONPATH':'backend:.'}
 subprocess.run([sys.executable,'-m','pytest','-q','tests/test_hilega_pcr_context_v1.py','tests/test_strike_positioning.py','tests/test_hilega_directional_live_shadow_ui_v1.py'],check=True,env=env)
 subprocess.run([sys.executable,'-m','py_compile','backend/market_lab/hilega_pcr_context_v1.py','backend/market_lab/api.py'],check=True)
 subprocess.run(['npm','--prefix','frontend','run','build'],check=True)
except BaseException:
 for p,exists in existed.items():
  if exists:shutil.copy2(backup/p.relative_to(root),p)
  else:p.unlink(missing_ok=True)
 if dist.exists():shutil.rmtree(dist)
 if had_dist:shutil.copytree(backup/'frontend-dist',dist)
 print('STOP: source and frontend build restored; no restart performed.');raise
print('PASS: compact PCR totals, selected audit cards and exact-strike active bias installed. Restart required. Backup:',backup)
