"""Performance-only source installer. No broker API or trading controls touched."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,shutil,subprocess,sys
root=Path.cwd();bundle=Path(__file__).resolve().parent;planned={}
api=root/'backend/market_lab/api.py'
if 'hilega_pcr_context_router' not in api.read_text():raise SystemExit('STOP: install PCR inspection v2 first; API route missing')
for rel,hashes in json.loads((bundle/'manifest.json').read_text()).items():
 p=root/rel
 if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() not in hashes.values():raise SystemExit('STOP: installed source differs from tested PCR v2: '+rel)
 planned[p]=(bundle/'files'/rel).read_bytes()
page=root/'frontend/src/hilegaMilegaShadow.tsx';s=page.read_text();old='setInterval(()=>void poll(),5000)';new='setInterval(()=>void poll(),15000)'
if new not in s:
 if s.count(old)!=1:raise SystemExit('STOP: Hilega polling anchor differs; source unchanged')
 s=s.replace(old,new,1)
planned[page]=s.encode()
backup=root/'data/backups'/('hilega-pcr-performance-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));backup.mkdir(parents=True)
for p in planned:
 target=backup/p.relative_to(root);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
dist=root/'frontend/dist';had=dist.exists()
if had:shutil.copytree(dist,backup/'frontend-dist')
try:
 for p,value in planned.items():p.write_bytes(value)
 env={**os.environ,'PYTHONPATH':'backend:.'}
 subprocess.run([sys.executable,'-m','pytest','-q','tests/test_hilega_pcr_context_v1.py','tests/test_strike_positioning.py','tests/test_hilega_directional_live_shadow_ui_v1.py'],check=True,env=env)
 subprocess.run([sys.executable,'-m','py_compile','backend/market_lab/hilega_pcr_context_v1.py'],check=True)
 subprocess.run(['npm','--prefix','frontend','run','build'],check=True)
except BaseException:
 for p in planned:shutil.copy2(backup/p.relative_to(root),p)
 if dist.exists():shutil.rmtree(dist)
 if had:shutil.copytree(backup/'frontend-dist',dist)
 print('STOP: validation failed; source and frontend build restored.');raise
print('PASS: bounded PCR reads, cached responses, shared/hidden-tab polling and 15s Hilega refresh installed.')
print('Restart API required. Strategy, Sandbox arm, collection config, database and orders unchanged. Backup:',backup)
