from pathlib import Path
import datetime,shutil,subprocess,sys,os
ROOT=Path.cwd();BUNDLE=Path(__file__).resolve().parent
worker=ROOT/'backend/market_lab/hilega_upstox_sandbox_live_worker_v1.py'
if not worker.exists():raise SystemExit('Run from RB-ITOS-AI root')
text=worker.read_text()
anchor='        for intent in eligible:\n'
insertion='''        for intent in eligible:
            from .hilega_sandbox_prearm_exit_guard_v1 import is_prearm_exit
            if is_prearm_exit(intent, intents, control, self.dispatch.rows()):
                self.dispatch.append({
                    "model": MODEL, "intent_id": intent["intent_id"],
                    "trade_id": intent["trade_id"], "event_type": "EXIT",
                    "event_timestamp": intent["event_timestamp"],
                    "direction": intent["direction"], "session_date": session_date,
                    "source_sequence": intent["source_sequence"],
                    "status": "SKIPPED_PRE_ARM_TRADE_EXIT", "terminal": True,
                    "reason": "Matching shadow entry preceded arming; no Sandbox submission exists",
                    "sandbox_only": True, "broker_called": False,
                    "live_order_sent": False, "timestamp": now.isoformat(),
                })
                skipped += 1
                continue
'''
if 'SKIPPED_PRE_ARM_TRADE_EXIT' not in text:
    if text.count(anchor)!=1:raise SystemExit('STOP: worker differs from expected loop; source untouched')
    text=text.replace(anchor,insertion)
files={worker:text}
for path in (BUNDLE/'files').rglob('*'):
    if path.is_file():files[ROOT/path.relative_to(BUNDLE/'files')]=path.read_text()
ui=ROOT/'frontend/src/hilegaExpiryWorkspace.tsx'
if ui.exists():
    u=ui.read_text()
    u=u.replace('running?:boolean}', 'running?:boolean;failure_reason?:string;failed_at?:string}')
    old="{worker?.armed?'Armed':'Disarmed / unavailable'} · kill switch {worker?.kill_switch===false?'OFF':'ON / unavailable'}"
    new="{worker?.armed===true?'Armed':worker?.armed===false?'Disarmed':'Arm state unavailable'} · kill switch {worker?.kill_switch===false?'OFF':worker?.kill_switch===true?'ON':'Unavailable'}{worker?.failure_reason&&<small>Reason: {worker.failure_reason} · {worker.failed_at??'Time unavailable'}</small>}"
    u=u.replace(old,new)
    files[ui]=u
backup=ROOT/'data/backups'/('hilega-prearm-exit-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
backup.mkdir(parents=True)
prior={}
for p in files:
    prior[p]=p.exists()
    if p.exists():
        b=backup/p.relative_to(ROOT);b.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,b)
try:
    for p,s in files.items():p.parent.mkdir(parents=True,exist_ok=True);p.write_text(s)
    env=dict(os.environ,PYTHONPATH='backend:.')
    subprocess.run([sys.executable,'-m','pytest','-q','tests/test_hilega_sandbox_prearm_exit_guard_v1.py','tests/test_hilega_upstox_sandbox_live_worker_v1.py','tests/test_hilega_sandbox_event_bridge_v1.py','tests/test_hilega_upstox_sandbox_execution_v1.py'],check=True,env=env)
    subprocess.run([sys.executable,'-m','py_compile',str(worker)],check=True)
    if ui.exists():subprocess.run(['npm','--prefix','frontend','run','build'],check=True)
    if (ROOT/'.git').exists():subprocess.run(['git','diff','--check'],check=True)
except Exception:
    for p,exists in prior.items():
        if exists:shutil.copy2(backup/p.relative_to(ROOT),p)
        else:p.unlink(missing_ok=True)
    raise SystemExit('STOP: source restored; rebuild frontend if necessary')
print('PASS: provable pre-arm exit skip installed; genuine mismatch guard retained.')
print('Worker control remains unchanged. Stop worker before install, then explicitly arm and start.')
print('No orders sent by installer. Backup:',backup)
