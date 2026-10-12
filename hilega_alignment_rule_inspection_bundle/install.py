import hashlib,json,os,shutil,subprocess,sys
from datetime import datetime
from pathlib import Path
B=Path(__file__).resolve().parent;R=B.parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 m=json.loads((B/"source-manifest.json").read_text())
 for rel,expected in m.items():
  p=R/rel
  if p.exists():
   if sha(p) not in {expected,sha(B/"files"/rel)}:raise SystemExit("STOP: source differs: "+rel)
  elif expected is not None:raise SystemExit("STOP: source missing: "+rel)
 backup=R/"data/backups"/("hilega-rule-inspection-"+datetime.now().strftime("%Y%m%dT%H%M%S%f"));backup.mkdir(parents=True)
 dist=R/"frontend/dist";had=dist.exists()
 if had:shutil.copytree(dist,backup/"frontend-dist")
 for rel in m:
  dest=backup/rel;dest.parent.mkdir(parents=True,exist_ok=True)
  if (R/rel).exists():shutil.copy2(R/rel,dest)
 env=os.environ.copy();env["PYTHONPATH"]=str(R/"backend")+os.pathsep+str(R)
 try:
  for rel in m:shutil.copy2(B/"files"/rel,R/rel)
  subprocess.run([sys.executable,"-m","pytest","-q","tests/test_hilega_alignment_audit_projection.py","tests/test_hilega_alignment_dual_exit_live_v1.py","tests/test_hilega_directional_candle_ui_v1.py"],cwd=R,env=env,check=True)
  subprocess.run(["npm","--prefix","frontend","run","build"],cwd=R,env=env,check=True)
 except BaseException:
  for rel in m:
   if (backup/rel).exists():shutil.copy2(backup/rel,R/rel)
   else:(R/rel).unlink(missing_ok=True)
  if dist.exists():shutil.rmtree(dist)
  if had:shutil.copytree(backup/"frontend-dist",dist)
  raise
 print("PASS: Rule-by-rule latest strategy inspection installed; no strategy, audit or order changes.")
 print("Backup:",backup)
if __name__=="__main__":main()
