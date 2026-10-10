import hashlib,os,shutil,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path.cwd();FILES=Path(__file__).resolve().parent/'files'
OLD_HASH='61d0bde62eb242d56d3a1d9b91aa1974a0b8beef3c95fe3170dc77d3079b08a6'

def main():
 target=Path('frontend/src/hilegaHistoricalReplay.tsx');current=ROOT/target
 if not current.is_file() or hashlib.sha256(current.read_bytes()).hexdigest() not in {OLD_HASH,hashlib.sha256((FILES/target).read_bytes()).hexdigest()}:raise SystemExit('STOP: source differs from the shared replay UI version; no files changed')
 if not (ROOT/'frontend/src/hilegaReplayTradeLedger.tsx').is_file():raise SystemExit('STOP: install the shared replay UI correction first')
 paths=[p.relative_to(FILES) for p in FILES.rglob('*') if p.is_file()]
 backup=ROOT/'data/backups'/('hilega-all-strategy-metrics-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));backup.mkdir(parents=True)
 existed={p:(ROOT/p).is_file() for p in paths}
 try:
  for p in paths:
   if existed[p]:dst=backup/p;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/p,dst)
   dst=ROOT/p;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(FILES/p,dst)
  for cmd in [['node','scripts/validate_hilega_replay_metrics.cjs'],['npm','--prefix','frontend','run','build']]:
   print('Running:',*cmd,flush=True);subprocess.run(cmd,cwd=ROOT,check=True)
 except Exception:
  for p in paths:
   if existed[p]:shutil.copy2(backup/p,ROOT/p)
   elif (ROOT/p).exists():(ROOT/p).unlink()
  print('STOP: source restored. Rebuild restored frontend if compilation started.');raise
 print('PASS: all four same-session strategy summaries populated; selected audit retained. Strategy and execution unchanged. Backup:',backup)
if __name__=='__main__':main()
