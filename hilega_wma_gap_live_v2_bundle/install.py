"""Install the reviewed V2 patch, validate, then select V2 in local .env."""
from __future__ import annotations
import hashlib,json,os,shutil,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
BUNDLE=Path(__file__).resolve().parent
ROOT=Path.cwd()
TESTS=[
 'tests/test_hilega_wma_gap_live_v2.py',
 'tests/test_hilega_milega_option_shadow_lifecycle_v1.py',
 'tests/test_hilega_directional_bootstrap_recovery_v1.py',
 'tests/test_hilega_directional_live_shadow_v1.py',
 'tests/test_hilega_sandbox_event_bridge_v1.py',
 'tests/test_hilega_upstox_sandbox_basket_v2.py',
 'tests/test_hilega_directional_coordinator_v1.py',
 'tests/test_shadow_session_recovery.py',
 'tests/test_hilega_directional_live_shadow_ui_v1.py',
 'tests/test_hilega_wma_gap_forward_publisher.py',
]
SELECTED='HILEGA_WMA_GAP_V2_LIVE_SHADOW'
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

def update_env(text):
    # Preserve all other settings verbatim. Never print the file or token values.
    lines=text.splitlines(keepends=True);prefix='LIVE_SHADOW_STRATEGY='
    found=[i for i,line in enumerate(lines) if line.strip().startswith(prefix)]
    if len(found)>1:raise ValueError('Duplicate LIVE_SHADOW_STRATEGY entries; resolve before install')
    if found:lines[found[0]]=prefix+SELECTED+'\n'
    else:
        if lines and not lines[-1].endswith('\n'):lines[-1]+='\n'
        lines.append(prefix+SELECTED+'\n')
    return ''.join(lines)

def main():
    if not (ROOT/'backend/market_lab').is_dir():raise SystemExit('STOP: run installer from ~/RB-ITOS-AI')
    env_path=ROOT/'.env'
    if not env_path.is_file():raise SystemExit('STOP: backend .env is missing')
    intended_env=update_env(env_path.read_text())
    pid_path=ROOT/'data/hilega-upstox-sandbox-worker.pid'
    if pid_path.exists():
        try:os.kill(int(pid_path.read_text().strip()),0)
        except (ValueError,ProcessLookupError):pass
        else:raise SystemExit('STOP: stop the Sandbox worker before installation')
    manifest=json.loads((BUNDLE/'manifest.json').read_text())
    for name,item in manifest.items():
        if digest(BUNDLE/'files'/name)!=item['installed_sha256']:raise SystemExit('STOP: bundle integrity failed: '+name)
        current=digest(ROOT/name)
        if current not in {item['before_sha256'],item['installed_sha256']}:
            raise SystemExit('STOP: source differs from the uploaded snapshot: '+name+'; no files changed')
    # Read-only reconciliation guard; no transport or network client is created.
    preflight=[sys.executable,'-c',
      'from market_lab.hilega_upstox_sandbox_basket_v2 import BasketStore, JOURNAL, ensure_clear; ensure_clear(BasketStore(JOURNAL)); '
      'from market_lab.hilega_upstox_sandbox_live_worker_v1 import DispatchStore, DEFAULT_DISPATCH; '
      's=DispatchStore(DEFAULT_DISPATCH); '
      'assert not any(s.open_trade(day) for day in {r.get("session_date") for r in s.rows() if r.get("session_date")}), "LEGACY_OPEN_SANDBOX_TRADE_RECONCILE_FIRST"']
    environment=dict(os.environ);environment['PYTHONPATH']=str(ROOT/'backend')+os.pathsep+str(ROOT)
    subprocess.run(preflight,cwd=ROOT,env=environment,check=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup=ROOT/'data/backups'/('hilega-wma-gap-live-v2-'+stamp);backup.mkdir(parents=True)
    prior={};dist=ROOT/'frontend/dist';had_dist=dist.exists()
    if had_dist:shutil.copytree(dist,backup/'frontend-dist')
    try:
        for name in manifest:
            dst=ROOT/name;prior[name]=dst.exists()
            if prior[name]:
                old=backup/name;old.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dst,old)
            dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(BUNDLE/'files'/name,dst)
        commands=[
            [sys.executable,'-m','pytest','-q',*TESTS],
            [sys.executable,'-m','py_compile',*[name for name in manifest if name.endswith('.py')]],
            ['npm','--prefix','frontend','run','build'],
        ]
        for command in commands:
            print('Running:', ' '.join(command),flush=True)
            subprocess.run(command,cwd=ROOT,env=environment,check=True)
        shutil.copy2(env_path,backup/'backend.env');os.chmod(backup/'backend.env',0o600)
        temporary=env_path.with_name('.env.v2-tmp');temporary.write_text(intended_env);os.chmod(temporary,0o600);temporary.replace(env_path)
    except Exception:
        for name,existed in prior.items():
            if existed:shutil.copy2(backup/name,ROOT/name)
            else:(ROOT/name).unlink(missing_ok=True)
        if dist.exists():shutil.rmtree(dist)
        if had_dist:shutil.copytree(backup/'frontend-dist',dist)
        print('STOP: validation failed; source and frontend dist restored. Strategy selection unchanged.')
        raise
    print('PASS: WMA-gap V2 installed and selected in .env; V1 is no longer the selected live shadow strategy.')
    print('Restart the application, then explicitly arm/start the five-leg Sandbox worker for the desired session.')
    print('No orders sent by installer. Structural exit retained. Backup:',backup)
if __name__=='__main__':main()
