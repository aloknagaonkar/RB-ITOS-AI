"""Disposable native arm protected by transient managed guard and stop recovery."""
import argparse,json,subprocess,sys,time,uuid
from pathlib import Path
from native import service
from window import intent,admit,save,need

def unit_arg(value):
    need('\n' not in value and '\r' not in value and '%' not in value,'UNSUPPORTED_SYSTEMD_ARGUMENT')
    return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('$','$$')+'"'

def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--workspace',type=Path,required=True);a=p.parse_args()
    s=service(a.bundle,a.workspace);c=s.store.control()
    s.command('reconcile',request_id=uuid.uuid4().hex,expected_version=c['version'],actor='DISPOSABLE_MANAGED_WINDOW',session_date=c['session_date']);c=s.store.control()
    with s.store.db() as db:cursor=json.loads(db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()[0])
    state=intent(version=c['version'],session=c['session_date'],sequence=cursor['sequence'],now=time.time(),duration=12);save(a.workspace/'WINDOW.json',state)
    unit='hilega-disposable-window-'+uuid.uuid4().hex+'.service'
    guard=[sys.executable,'-B',str(Path(__file__).with_name('managed_guard.py')),'--bundle',str(a.bundle),'--workspace',str(a.workspace)]
    recovery=' '.join(unit_arg(x) for x in guard+['--recover'])
    command=['systemd-run','--user','--unit='+unit,'--property=Type=exec','--property=Restart=no',
        '--property=RuntimeMaxSec=25','--property=TimeoutStopSec=10','--property=UMask=0077',
        '--property=ExecStopPost='+recovery,'--property=StandardOutput=append:'+str(a.workspace/'guard.log'),
        '--property=StandardError=append:'+str(a.workspace/'guard.log'),'--working-directory='+str(a.workspace),
        '--setenv=PYTHONDONTWRITEBYTECODE=1','--setenv=HILEGA_PRODUCTION_EXECUTION_ROUTE=PREPARATION_ONLY',
        '--setenv=HILEGA_PRODUCTION_WORKSPACE_MODE=SIMULATION_ONLY',*guard]
    started=False
    try:
        need(subprocess.run(command,capture_output=True,text=True,timeout=10).returncode==0,'DISPOSABLE_MANAGED_GUARD_START_FAILED');started=True
        save(a.workspace/'MANAGED-UNIT.json',dict(unit=unit,transient=True,application_unit=False))
        until=time.monotonic()+6
        while not (a.workspace/'GUARD-READY').exists():need(time.monotonic()<until,'MANAGED_GUARD_NOT_READY');time.sleep(.1)
        current=dict(mode=c['mode'],version=c['version'],session=c['session_date'],empty=True,route='PREPARATION_ONLY',gate_closed=True)
        save(a.workspace/'WINDOW.json',admit(state,current,now=time.time(),guard_ready=True))
        s.command('resume',request_id=uuid.uuid4().hex,expected_version=c['version'],actor='DISPOSABLE_MANAGED_WINDOW',session_date=c['session_date'])
        need(s.store.control()['mode']=='ARMED','NATIVE_ARM_FAILED');save(a.workspace/'ARMED.json',dict(native_command_used=True))
        if a.workspace.name=='managed-guard-loss':
            need(subprocess.run(['systemctl','--user','kill','--kill-whom=main','--signal=SIGKILL',unit],capture_output=True,timeout=10).returncode==0,'DISPOSABLE_GUARD_KILL_FAILED')
        until=time.monotonic()+22
        while not (a.workspace/'GUARD-RESULT.json').exists():need(time.monotonic()<until,'MANAGED_PAUSE_TIMEOUT');time.sleep(.1)
        need(s.store.control()['mode']=='PAUSED','MANAGED_WINDOW_LEFT_ARMED')
    finally:
        if started:subprocess.run(['systemctl','--user','stop',unit],capture_output=True,timeout=15)
        if s.store.control()['mode']!='PAUSED':
            c=s.store.control();s.command('pause',request_id=uuid.uuid4().hex,expected_version=c['version'],actor='DISPOSABLE_MANAGED_CLEANUP',session_date=c['session_date'])
        if started:subprocess.run(['systemctl','--user','reset-failed',unit],capture_output=True,timeout=10)
    need((a.workspace/'STOP-RECOVERY.json').exists(),'MANAGED_STOP_POST_NOT_VERIFIED')
    # Repeat persisted-state recovery after the managed process is gone. This is not a reboot test.
    need(subprocess.run(guard+['--recover'],capture_output=True,text=True,timeout=10).returncode==0,'PERSISTED_DISPOSABLE_RECOVERY_FAILED')
    save(a.workspace/'MANAGED-COMPLETE.json',dict(stop_recovery_verified=True,persisted_state_recovery_repeated=True,actual_reboot_tested=False));return 0
if __name__=='__main__':raise SystemExit(main())
