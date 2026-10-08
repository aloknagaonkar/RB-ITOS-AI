from pathlib import Path
import os,shutil,subprocess,sys
from datetime import datetime,timezone
ROOT=Path.cwd();B=Path(__file__).resolve().parent
api=ROOT/'backend/market_lab/hilega_upstox_sandbox_dashboard_v1.py'
if not api.exists():raise SystemExit('STOP: run from RB-ITOS-AI root with existing Sandbox dashboard')
pidfile=ROOT/'data/hilega-upstox-sandbox-worker.pid'
if pidfile.exists():
    try:os.kill(int(pidfile.read_text()),0)
    except (OSError,ValueError):pass
    else:raise SystemExit('STOP: stop the Sandbox worker before installing')
files={}
for p in (B/'files').rglob('*'):
    if p.is_file():files[ROOT/p.relative_to(B/'files')]=p.read_text()
s=api.read_text();anchor='    control = JsonControl(control_path).read()\n'
addition='''    from .hilega_upstox_sandbox_basket_v2 import CONTROL as BASKET_CONTROL, build_dashboard as basket_dashboard
    if control_path == DEFAULT_CONTROL and dispatch_path == DEFAULT_DISPATCH and BASKET_CONTROL.exists():
        return basket_dashboard(env_path)
'''
if 'basket_dashboard(env_path)' not in s:
    if s.count(anchor)!=1:raise SystemExit('STOP: dashboard source differs; no changes made')
    s=s.replace(anchor,addition+anchor)
files[api]=s
for name in ('start_hilega_upstox_sandbox_worker.sh','status_hilega_upstox_sandbox_worker.sh'):
    p=ROOT/'scripts'/name;s=p.read_text()
    if 'market_lab.hilega_upstox_sandbox_live_worker_v1' not in s and 'market_lab.hilega_upstox_sandbox_basket_v2' not in s:raise SystemExit('STOP: worker script differs')
    files[p]=s.replace('market_lab.hilega_upstox_sandbox_live_worker_v1','market_lab.hilega_upstox_sandbox_basket_v2')
backup=ROOT/'data/backups'/('hilega-sandbox-five-leg-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));backup.mkdir(parents=True)
prior={p:p.exists() for p in files}
for p in files:
    if p.exists():
        b=backup/p.relative_to(ROOT);b.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,b)
try:
    for p,s in files.items():p.parent.mkdir(parents=True,exist_ok=True);p.write_text(s)
    env=dict(os.environ,PYTHONPATH='backend:.')
    subprocess.run([sys.executable,'-m','pytest','-q','tests/test_hilega_upstox_sandbox_basket_v2.py','tests/test_hilega_sandbox_event_bridge_v1.py','tests/test_hilega_sandbox_prearm_exit_guard_v1.py','tests/test_hilega_upstox_sandbox_execution_v1.py','tests/test_hilega_upstox_sandbox_dashboard_v1.py'],check=True,env=env)
    subprocess.run([sys.executable,'-m','py_compile',str(api),'backend/market_lab/hilega_upstox_sandbox_basket_v2.py'],check=True)
    subprocess.run(['npm','--prefix','frontend','run','build'],check=True)
    if (ROOT/'.git').exists():subprocess.run(['git','diff','--check'],check=True)
except Exception:
    for p,had in prior.items():
        if had:shutil.copy2(backup/p.relative_to(ROOT),p)
        else:p.unlink(missing_ok=True)
    raise SystemExit('STOP: source restored; frontend dist may need rebuilding')
# V2 control is created only if absent; never adopt or arm an old position.
control=ROOT/'data/live-observation/hilega-upstox-sandbox-v2/control.json'
if not control.exists():
    control.parent.mkdir(parents=True,exist_ok=True)
    import json
    control.write_text(json.dumps(dict(model='HILEGA_UPSTOX_SANDBOX_BASKET_V2',armed=False,kill_switch=True,execution_mode='FIVE_ACTUAL_SANDBOX_LEGS',order_count_limit=None,max_orders=None,sandbox_only=True,live_execution_enabled=False),indent=2))
print('PASS: five actual Sandbox legs per signal installed. No orders sent. Daily order-count cap removed for V2.')
print('Restart API, explicitly arm V2 for current session and start worker. One-contract history preserved. Backup:',backup)
