from pathlib import Path
import os,shutil,subprocess,sys
from datetime import datetime,timezone
ROOT=Path.cwd();B=Path(__file__).resolve().parent
page=ROOT/'frontend/src/hilegaUpstoxSandboxDashboard.tsx'
backend=ROOT/'backend/market_lab/hilega_upstox_sandbox_dashboard_v1.py'
if not page.exists():raise SystemExit('STOP: run from repository root with Sandbox dashboard installed')
text=page.read_text()
if "import HilegaSandboxFiveStrikeView from" not in text:
    text="import HilegaSandboxFiveStrikeView from './hilegaSandboxFiveStrikeView'\n"+text
anchor='    <section className="panel shadow-panel"><div className="panel-heading"><div><h2>Blocked and failed sandbox events</h2>'
if '<HilegaSandboxFiveStrikeView/>' not in text:
    if text.count(anchor)!=1:raise SystemExit('STOP: expected dashboard section differs; source untouched')
    text=text.replace(anchor,'    <HilegaSandboxFiveStrikeView/>\n\n'+anchor)
files={page:text}
for p in (B/'files').rglob('*'):
    if p.is_file():files[ROOT/p.relative_to(B/'files')]=p.read_text()
if backend.exists():
    s=backend.read_text()
    old='"completed_trades": sorted(closed, key=lambda x: str(x["exit_time"]), reverse=True),'
    new='"completed_trades": sorted([x for x in trades if x["status"] == "CLOSED"], key=lambda x: str(x["exit_time"]), reverse=True),'
    if old in s:s=s.replace(old,new);files[backend]=s
    elif new not in s:raise SystemExit('STOP: completed-trade projection differs; source untouched')
backup=ROOT/'data/backups'/('hilega-sandbox-five-strike-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));backup.mkdir(parents=True)
exists={p:p.exists() for p in files}
for p in files:
    if p.exists():
        dst=backup/p.relative_to(ROOT);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dst)
try:
    for p,s in files.items():p.parent.mkdir(parents=True,exist_ok=True);p.write_text(s)
    subprocess.run(['node',str(B/'test_model.mjs')],check=True)
    if backend.exists():
        env=dict(os.environ,PYTHONPATH='backend:.')
        subprocess.run([sys.executable,'-m','pytest','-q','tests/test_hilega_upstox_sandbox_dashboard_v1.py'],check=True,env=env)
        subprocess.run([sys.executable,'-m','py_compile',str(backend)],check=True)
    subprocess.run(['npm','--prefix','frontend','run','build'],check=True)
    if (ROOT/'.git').exists():subprocess.run(['git','diff','--check'],check=True)
except Exception:
    for p,had in exists.items():
        if had:shutil.copy2(backup/p.relative_to(ROOT),p)
        else:p.unlink(missing_ok=True)
    raise SystemExit('STOP: source restored; frontend dist may need rebuilding')
print('PASS: five-strike shadow comparison and selected Sandbox order details installed.')
print('No orders, worker control, quantity, max orders or strategy changes. Refresh UI; API restart required for completed rows with missing prices.')
print('Backup:',backup)
