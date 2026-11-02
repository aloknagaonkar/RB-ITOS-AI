"""Disposable native arm with independent guard installed before resume."""
import argparse,json,subprocess,sys,time,uuid
from pathlib import Path
from native import service
from window import intent,admit,save,need

def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--workspace',type=Path,required=True);a=p.parse_args()
    s=service(a.bundle,a.workspace)
    c=s.store.control();s.command('reconcile',request_id=uuid.uuid4().hex,expected_version=c['version'],actor='DISPOSABLE_WINDOW_REHEARSAL',session_date=c['session_date'])
    c=s.store.control()
    with s.store.db() as db:
        cursor=json.loads(db.execute('SELECT data FROM preparation_source WHERE id=1').fetchone()[0])
        empty=all(db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]==0 for t in ('intents','sim_orders','sim_fills','preparation_plans','preparation_outbox','preparation_shadow_holds'))
    state=intent(version=c['version'],session=c['session_date'],sequence=cursor['sequence'],now=time.time(),duration=12)
    save(a.workspace/'WINDOW.json',state)
    guard=subprocess.Popen([sys.executable,'-B',str(Path(__file__).with_name('guard.py')),'--bundle',str(a.bundle),'--workspace',str(a.workspace)],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    save(a.workspace/'GUARD-PROCESS.json',dict(pid=guard.pid))
    try:
        until=time.monotonic()+5
        while not (a.workspace/'GUARD-READY').exists():
            need(guard.poll() is None and time.monotonic()<until,'WATCHDOG_NOT_READY');time.sleep(.1)
        current=dict(mode=c['mode'],version=c['version'],session=c['session_date'],empty=empty,route='PREPARATION_ONLY',gate_closed=True)
        state=admit(state,current,now=time.time(),guard_ready=guard.poll() is None)
        save(a.workspace/'WINDOW.json',state)
        s.command('resume',request_id=uuid.uuid4().hex,expected_version=c['version'],actor='DISPOSABLE_BOUNDED_PREPARATION',session_date=c['session_date'])
        need(s.store.control()['mode']=='ARMED','NATIVE_ARM_NOT_VERIFIED')
        save(a.workspace/'ARMED.json',dict(native_command_used=True,source_sequence=cursor['sequence']))
        while guard.poll() is None:time.sleep(.2)
        need(guard.returncode==0 and s.store.control()['mode']=='PAUSED','DEADLINE_PAUSE_FAILED');return 0
    finally:
        # This executes for ordinary failure. SIGKILL rehearsal relies on the independent guard.
        if s.store.control()['mode']!='PAUSED':
            c=s.store.control();s.command('pause',request_id=uuid.uuid4().hex,expected_version=c['version'],actor='DISPOSABLE_WINDOW_CLEANUP',session_date=c['session_date'])
if __name__=='__main__':raise SystemExit(main())
