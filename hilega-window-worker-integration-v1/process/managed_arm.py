"""Disposable native arm protected by transient managed guard and stop recovery."""
import argparse,fcntl,json,os,stat,subprocess,sys,time,uuid
from pathlib import Path
from native import service
from window import intent,admit,save,need

def unit_arg(value):
    need('\n' not in value and '\r' not in value and '%' not in value,'UNSUPPORTED_SYSTEMD_ARGUMENT')
    return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('$','$$')+'"'

def user_bus_environment(runtime=None):
    runtime=Path(runtime) if runtime is not None else Path('/run/user')/str(os.getuid())
    need(runtime.is_dir() and not any(x.is_symlink() for x in [runtime,*runtime.absolute().parents]),'REGULAR_USER_RUNTIME_DIRECTORY_REQUIRED')
    info=runtime.stat();need(info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)&0o077==0,'PRIVATE_OWNED_USER_RUNTIME_REQUIRED')
    bus=runtime/'bus';need(not bus.is_symlink() and stat.S_ISSOCK(bus.stat().st_mode) and bus.stat().st_uid==os.getuid(),'OWNED_USER_SESSION_BUS_REQUIRED')
    environment=dict(os.environ)
    environment['XDG_RUNTIME_DIR']=str(runtime)
    environment['DBUS_SESSION_BUS_ADDRESS']='unix:path='+str(bus)
    return environment

def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--workspace',type=Path,required=True);a=p.parse_args()
    s=service(a.bundle,a.workspace);c=s.store.control()
    s.command('reconcile',request_id=uuid.uuid4().hex,expected_version=c['version'],actor='DISPOSABLE_MANAGED_WINDOW',session_date=c['session_date']);c=s.store.control()
    with s.store.db() as db:cursor=json.loads(db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()[0])
    state=intent(version=c['version'],session=c['session_date'],sequence=cursor['sequence'],now=time.time(),duration=30)
    with s.store.db() as db:state['source_lease']=json.loads(db.execute('SELECT data FROM sim_bridge_health WHERE id=1').fetchone()[0])['run_id']
    save(a.workspace/'WINDOW.json',state)
    unit='hilega-disposable-window-'+uuid.uuid4().hex+'.service'
    guard=[sys.executable,'-B',str(Path(__file__).with_name('managed_guard.py')),'--bundle',str(a.bundle),'--workspace',str(a.workspace)]
    recovery=' '.join(unit_arg(x) for x in guard+['--recover'])
    command=['systemd-run','--user','--unit='+unit,'--property=Type=exec','--property=Restart=no',
        '--property=RuntimeMaxSec=45','--property=TimeoutStopSec=10','--property=UMask=0077',
        '--property=ExecStopPost='+recovery,'--property=StandardOutput=append:'+str(a.workspace/'guard.log'),
        '--property=StandardError=append:'+str(a.workspace/'guard.log'),'--working-directory='+str(a.workspace),
        '--setenv=PYTHONDONTWRITEBYTECODE=1','--setenv=HILEGA_PRODUCTION_EXECUTION_ROUTE=PREPARATION_ONLY',
        '--setenv=HILEGA_PRODUCTION_WORKSPACE_MODE=SIMULATION_ONLY',*guard]
    manager_env=user_bus_environment()
    save(a.workspace/'MANAGED-UNIT.json',dict(unit=unit,transient=True,application_unit=False))
    started=False
    try:
        launch=subprocess.run(command,capture_output=True,text=True,timeout=10,env=manager_env)
        save(a.workspace/'MANAGED-LAUNCH.json',dict(exit_code=launch.returncode,stdout=launch.stdout,stderr=launch.stderr))
        need(launch.returncode==0,'DISPOSABLE_MANAGED_GUARD_START_FAILED; inspect MANAGED-LAUNCH.json');started=True
        until=time.monotonic()+6
        while not (a.workspace/'GUARD-READY').exists():need(time.monotonic()<until,'MANAGED_GUARD_NOT_READY');time.sleep(.1)
        with s.store.db() as db:
            empty=all(db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]==0 for t in ('intents','sim_orders','sim_fills','preparation_plans','preparation_outbox','preparation_shadow_holds'))
        current=dict(mode=c['mode'],version=c['version'],session=c['session_date'],empty=empty,route='PREPARATION_ONLY',gate_closed=True)
        with (a.workspace/'WINDOW-ARM-PAUSE.lock').open('a+') as window_lock:
            fcntl.flock(window_lock,fcntl.LOCK_EX)
            live=subprocess.run(['systemctl','--user','show',unit,'--property=ActiveState,MainPID'],capture_output=True,text=True,timeout=10,env=manager_env)
            fields=dict(line.split('=',1) for line in live.stdout.splitlines() if '=' in line)
            need(live.returncode==0 and fields.get('ActiveState')=='active' and int(fields.get('MainPID','0'))>0 and not (a.workspace/'GUARD-PAUSE-INTENT.json').exists(),'GUARD_LOST_BEFORE_NATIVE_RESUME')
            save(a.workspace/'WINDOW.json',admit(state,current,now=time.time(),guard_ready=True))
            s.command('resume',request_id=uuid.uuid4().hex,expected_version=c['version'],actor='DISPOSABLE_MANAGED_WINDOW',session_date=c['session_date'])
            need(s.store.control()['mode']=='ARMED','NATIVE_ARM_FAILED');save(a.workspace/'ARMED.json',dict(native_command_used=True))
        if a.workspace.name=='managed-guard-loss':
            need(subprocess.run(['systemctl','--user','kill','--kill-whom=main','--signal=SIGKILL',unit],capture_output=True,timeout=10,env=manager_env).returncode==0,'DISPOSABLE_GUARD_KILL_FAILED')
        until=time.monotonic()+40
        while not (a.workspace/'GUARD-RESULT.json').exists():need(time.monotonic()<until,'MANAGED_PAUSE_TIMEOUT');time.sleep(.1)
        need(s.store.control()['mode']=='PAUSED','MANAGED_WINDOW_LEFT_ARMED')
    finally:
        subprocess.run(['systemctl','--user','stop',unit],capture_output=True,timeout=15,env=manager_env)
        if s.store.control()['mode']!='PAUSED':
            c=s.store.control();s.command('pause',request_id=uuid.uuid4().hex,expected_version=c['version'],actor='DISPOSABLE_MANAGED_CLEANUP',session_date=c['session_date'])
        if started:subprocess.run(['systemctl','--user','reset-failed',unit],capture_output=True,timeout=10,env=manager_env)
    need((a.workspace/'STOP-RECOVERY.json').exists(),'MANAGED_STOP_POST_NOT_VERIFIED')
    # Repeat persisted-state recovery after the managed process is gone. This is not a reboot test.
    need(subprocess.run(guard+['--recover'],capture_output=True,text=True,timeout=10).returncode==0,'PERSISTED_DISPOSABLE_RECOVERY_FAILED')
    save(a.workspace/'WINDOW.json',dict(state,phase='CLOSED'))
    save(a.workspace/'MANAGED-COMPLETE.json',dict(stop_recovery_verified=True,persisted_state_recovery_repeated=True,actual_reboot_tested=False));return 0
if __name__=='__main__':raise SystemExit(main())
