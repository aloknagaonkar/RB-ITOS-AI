"""Independent disposable-only deadline watchdog; supports explicit recovery after interruption."""
import argparse,json,time,uuid
from pathlib import Path
from native import service
from window import decision,save

def pause_native(s):
    c=s.store.control()
    s.command('pause',request_id=uuid.uuid4().hex,expected_version=c['version'],actor='DISPOSABLE_WINDOW_GUARD',session_date=c['session_date'])
    if s.store.control()['mode']!='PAUSED':raise ValueError('PAUSE_NOT_VERIFIED')

def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--workspace',type=Path,required=True);p.add_argument('--recover',action='store_true');a=p.parse_args()
    s=service(a.bundle,a.workspace);path=a.workspace/'WINDOW.json';state=json.loads(path.read_text())
    (a.workspace/'GUARD-READY').write_text('READY\n')
    while True:
        c=s.store.control()
        with s.store.db() as db:n=db.execute('SELECT COUNT(*) FROM preparation_plans').fetchone()[0]
        # Before arm, PAUSED is expected; remain ready until deadline or explicit recovery.
        action=decision(state,now=time.time(),mode=c['mode'],preparations=n)
        if a.recover or action in {'PAUSE_ON_PREPARATION','PAUSE_ON_CLOCK_REWIND','PAUSE_ON_DEADLINE'} or time.time()>=state['deadline']:
            pause_native(s)
            save(a.workspace/'GUARD-RESULT.json',dict(status='DISPOSABLE_WINDOW_PAUSED',trigger='RECOVERY' if a.recover else action,production_execution_enabled=False));return 0
        time.sleep(.2)
if __name__=='__main__':raise SystemExit(main())
