from pathlib import Path
import os, shutil, subprocess, sys
from datetime import datetime, timezone
ROOT=Path.cwd(); FILES=Path(__file__).resolve().parent/"files"
backup=ROOT/"data/backups"/("hilega-v2-audit-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
changes=[]
try:
    for source in FILES.rglob("*"):
        if not source.is_file():continue
        relative=source.relative_to(FILES);target=ROOT/relative; saved=backup/relative
        exists=target.exists()
        if exists:saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
        changes.append((target,saved,exists));target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    env={**os.environ,"PYTHONPATH":"backend:."}
    subprocess.run([sys.executable,"-m","pytest","-q","tests/test_hilega_v2_decision_audit_fix.py","tests/test_hilega_historical_ui_api_v1.py"],check=True,env=env)
    subprocess.run(["npm","--prefix","frontend","run","build"],check=True)
except Exception:
    for target,saved,exists in reversed(changes):
        if exists:shutil.copy2(saved,target)
        else:target.unlink(missing_ok=True)
    print("STOP: source restored; rebuild frontend if its build failed.");raise
print("PASS: V2 decision audit fix installed. Restart required. Backup:",backup)
