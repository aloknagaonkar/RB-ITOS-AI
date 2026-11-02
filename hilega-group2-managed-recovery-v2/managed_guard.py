"""Disposable managed deadline guard and ExecStopPost pause recovery."""
import argparse,json,time,uuid
from pathlib import Path
from native import service
from window import save

def recover(s):
    c=s.store.control()
    s.command('pause',request_id=uuid.uuid4().hex,expected_version=c['version'],actor='DISPOSABLE_MANAGED_RECOVERY',session_date=c['session_date'])
    if s.store.control()['mode']!='PAUSED':raise ValueError('RECOVERY_PAUSE_FAILED')

def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--workspace',type=Path,required=True);p.add_argument('--recover',action='store_true');a=p.parse_args()
    s=service(a.bundle,a.workspace);state=json.loads((a.workspace/'WINDOW.json').read_text())
    if a.recover:
        recover(s);save(a.workspace/'STOP-RECOVERY.json',dict(status='PAUSED',explicit_recovery=True))
        if not (a.workspace/'GUARD-RESULT.json').exists():save(a.workspace/'GUARD-RESULT.json',dict(trigger='MANAGED_STOP_RECOVERY'))
        return 0
    (a.workspace/'GUARD-READY').write_text('READY\n')
    while True:
        now=time.time()
        with s.store.db() as db:n=db.execute('SELECT COUNT(*) FROM preparation_plans').fetchone()[0]
        if now>=state['deadline'] or now<state['created_at'] or n:
            recover(s);save(a.workspace/'GUARD-RESULT.json',dict(trigger='PAUSE_ON_DEADLINE' if now>=state['deadline'] else 'PAUSE_ON_PREPARATION_OR_CLOCK_REWIND'));return 0
        time.sleep(.2)
if __name__=='__main__':raise SystemExit(main())
