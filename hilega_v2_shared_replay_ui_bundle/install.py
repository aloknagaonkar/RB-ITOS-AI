"""Guarded shared historical UI installer for the supplied October 10 source."""
import hashlib, os, shutil, subprocess, sys
from pathlib import Path
from datetime import datetime, timezone
ROOT=Path.cwd();FILES=Path(__file__).resolve().parent/'files'
EXPECTED={'backend/market_lab/hilega_historical_ui_api_v1.py': '7fa2dfb62add3cdaa2bd7e5dc7be7d7b04f236cb96a02efc1ec04e9dc7f14b1e', 'frontend/src/hilegaHistoricalReplay.tsx': 'e31a84c55a63bc25648c18ca0727b4bae16b26066b37ee9be95ae0b62ec8561f', 'frontend/src/hilegaDecisionTable.tsx': 'dd41dcc132e1ac12a1bfaf66d262266b5430445a64f93f0285592812b782494e'}

def main():
 paths=[p.relative_to(FILES) for p in FILES.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
 for name,old in EXPECTED.items():
  p=ROOT/name;new=FILES/name
  if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() not in {old,hashlib.sha256(new.read_bytes()).hexdigest()}:
   raise SystemExit('STOP: source differs from supplied version: '+name+'; no files changed')
 if not (ROOT/'backend/market_lab/hilega_v2_alignment_replay_v1.py').is_file():raise SystemExit('STOP: automatic alignment replay foundation missing')
 backup=ROOT/'data/backups'/('hilega-v2-shared-replay-ui-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
 existed={p:(ROOT/p).is_file() for p in paths};backup.mkdir(parents=True)
 try:
  for p in paths:
   if existed[p]:
    dst=backup/p;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/p,dst)
   dst=ROOT/p;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(FILES/p,dst)
  env={**os.environ,'PYTHONPATH':str(ROOT/'backend')+os.pathsep+str(ROOT)}
  checks=[[sys.executable,'-m','unittest','discover','-s','tests','-p','test_hilega_v2_replay_presentation_v1.py'],
   [sys.executable,'-m','unittest','discover','-s','tests','-p','test_hilega_v2_alignment_auto_replay.py'],
   [sys.executable,'-m','py_compile','backend/market_lab/hilega_v2_replay_presentation_v1.py','backend/market_lab/hilega_historical_ui_api_v1.py'],
   ['node','scripts/validate_hilega_shared_replay_ui.cjs'],['npm','--prefix','frontend','run','build']]
  for cmd in checks:
   print('Running:',*cmd,flush=True);subprocess.run(cmd,cwd=ROOT,env=env,check=True)
 except Exception:
  for p in paths:
   if existed[p]:shutil.copy2(backup/p,ROOT/p)
   elif (ROOT/p).exists():(ROOT/p).unlink()
  print('STOP: installed source restored. If frontend compilation started, rebuild restored frontend before restarting.');raise
 print('PASS: V2 research replay uses shared trade/audit flow. Automatic date replay retained; entry/exit rules and live execution unchanged. Backup:',backup)
if __name__=='__main__':main()
