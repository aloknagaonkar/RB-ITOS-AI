"""Independent VWAP collector supervisor. Never imports trading workers."""
import argparse
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data/live-observation/hilega-vwap-signal-v1'
PID=DATA/'service.json'
SCRIPT=Path(__file__).resolve()
COLLECTOR=ROOT/'hilega_vwap_signal_review/collect.py'
PYTHON=ROOT/'.venv/bin/python'


def now():return datetime.now(timezone.utc).isoformat()


def ticks(pid):
    try:return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]
    except (OSError,IndexError):return None


def identity():
    try:
        r=json.loads(PID.read_text());pid=int(r['pid'])
        command=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        if r['root']!=str(ROOT) or str(SCRIPT).encode() not in command or b'run' not in command or ticks(pid)!=r['start_ticks']:
            return None
        return r
    except (OSError,ValueError,KeyError,TypeError):return None


def save(row):
    temporary=PID.with_suffix('.tmp');temporary.write_text(json.dumps(row,indent=2)+'\n');os.replace(temporary,PID)


def status():
    row=identity()
    print('VWAP collector: '+('RUNNING' if row else 'STOPPED'))
    evidence={}
    try:
        report=json.loads((DATA/'report.json').read_text())
        rows=report.get('rows',[])
        evidence=dict(record_count=len(rows),available_count=sum(r.get('status')=='AVAILABLE' for r in rows),
                      report_updated_at=datetime.fromtimestamp((DATA/'report.json').stat().st_mtime,timezone.utc).isoformat())
    except (OSError,ValueError,TypeError):pass
    print(json.dumps(dict(observation_only=True,entry_filter_enabled=False,supervisor=row,**evidence),indent=2))


def start():
    DATA.mkdir(parents=True,exist_ok=True)
    row=identity()
    if row:
        print(f'VWAP collector: already managed (PID {row["pid"]})');return
    if not PYTHON.is_file() or not COLLECTOR.is_file():
        raise SystemExit('VWAP collector: missing venv or hilega_vwap_signal_review/collect.py')
    # Do not duplicate or kill a previously launched manual watch process.
    with (DATA/'collector.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('VWAP collector: unmanaged collector already running; stop that process before managed startup') from None
    with (DATA/'service.log').open('ab') as log:
        child=subprocess.Popen([str(PYTHON),str(SCRIPT),'run'],cwd=ROOT,stdin=subprocess.DEVNULL,
                               stdout=log,stderr=log,start_new_session=True,close_fds=True)
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        if identity():
            print(f'VWAP collector: supervisor started (PID {identity()["pid"]}); observation only');return
        if child.poll() is not None:break
        time.sleep(.1)
    raise SystemExit('VWAP collector: startup failed; check data/live-observation/hilega-vwap-signal-v1/service.log')


def stop():
    row=identity()
    if not row:
        print('VWAP collector: no managed service running');return
    try:os.kill(row['pid'],signal.SIGTERM)
    except ProcessLookupError:return
    deadline=time.monotonic()+15
    while time.monotonic()<deadline and identity():time.sleep(.2)
    if identity():raise SystemExit('VWAP collector: still stopping; inspect service.log')
    print('VWAP collector: stopped')


def run():
    DATA.mkdir(parents=True,exist_ok=True)
    with (DATA/'supervisor.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state=dict(pid=os.getpid(),start_ticks=ticks(os.getpid()),root=str(ROOT),started_at=now(),child_pid=None,restarts=0,last_child_exit=None)
        stopped=False
        def shutdown(*_):
            nonlocal stopped
            stopped=True
        signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
        env=dict(os.environ);env['PYTHONPATH']=str(ROOT/'backend')+os.pathsep+str(ROOT)+(os.pathsep+env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
        child=None;delay=5
        try:
            save(state)
            while not stopped:
                with (DATA/'collector.log').open('ab') as log:
                    child=subprocess.Popen([str(PYTHON),str(COLLECTOR),'--watch','--output',str(DATA)],
                        cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,close_fds=True)
                state.update(child_pid=child.pid,child_started_at=now());save(state)
                started=time.monotonic()
                while not stopped and child.poll() is None:time.sleep(.5)
                if stopped:break
                state.update(child_pid=None,restarts=state['restarts']+1,last_child_exit=child.returncode,last_child_exit_at=now());save(state)
                if time.monotonic()-started>300:delay=5
                deadline=time.monotonic()+delay
                while not stopped and time.monotonic()<deadline:time.sleep(.5)
                delay=min(60,delay*2)
        finally:
            if child and child.poll() is None:
                child.terminate()
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=3)
            if identity() and identity()['pid']==os.getpid():PID.unlink(missing_ok=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['start','stop','status','run'])
    args=parser.parse_args();globals()[args.action]()
