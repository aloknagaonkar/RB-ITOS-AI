"""Real subprocess lifecycle validation; isolated simulator and synthetic journal only."""
import argparse,fcntl,hashlib,json,os,signal,subprocess,sys,time,uuid
from datetime import datetime
from pathlib import Path
import journal_support as j

CLI_SHA='114b44f5474ea880eb10388706b83fcaa335bb4546cede924ac3bb008ce7c772'

def child_env(root,db):
    # Do not inherit broker tokens, app control secrets or production flags.
    env={k:os.environ[k] for k in ('PATH','LANG','LC_ALL','SYSTEMROOT') if k in os.environ}
    env.update(PYTHONPATH=str(root/'backend')+os.pathsep+str(root),PYTHONUNBUFFERED='1',
        HILEGA_PRODUCTION_WORKSPACE_MODE='SIMULATION_ONLY',HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED='1',
        HILEGA_PRODUCTION_SIM_DB=str(db),TZ='Asia/Kolkata')
    return env

def append(path,names):
    previous=j.b.verified_records(path);at=datetime.now(j.IST).replace(second=0,microsecond=0)
    at=at.replace(minute=at.minute-at.minute%5);stamp=at.isoformat()
    row=dict(sequence=len(previous)+1,previous_hash=previous[-1]['record_hash'] if previous else None,
        stage='DIRECTIONAL_DECISION',status='PROCESSED',payload=dict(policy_id=j.b.POLICY,strategy_version=j.b.VERSION,
        reconstructed=False,decision_timestamp=stamp,accepted_events=names,event_details=[dict(event_type=n,event_time=stamp,
        entry_time=stamp,qualified_signal_time=stamp) for n in names]))
    row['record_hash']=hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
    with path.open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX);f.write(json.dumps(row)+'\n');f.flush();os.fsync(f.fileno())
    return row['sequence']

def latest(log):
    rows=[]
    if log.exists():
        for line in log.read_text().splitlines():
            try:rows.append(json.loads(line))
            except ValueError:pass
    return rows[-1] if rows else {}

def wait_for(label,predicate,process=None,timeout=25):
    print('CHECK: '+label,flush=True);deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate():return
        if process is not None and process.poll() is not None:raise RuntimeError('WORKER_EXITED_DURING_'+label.replace(' ','_'))
        time.sleep(.25)
    raise RuntimeError('TIMEOUT_'+label.replace(' ','_'))

def run(output,root):
    j.installed();cli=root/'scripts/hilega_production_simulator_bridge.py'
    if hashlib.sha256(cli.read_bytes()).hexdigest()!=CLI_SHA:raise j.Blocked('INSTALLED_WATCH_CLI_HASH_MISMATCH')
    if output.exists():raise j.Blocked('OUTPUT_EXISTS_USE_FRESH_DIRECTORY')
    output.mkdir(parents=True,mode=0o700);output=output.resolve()
    source=output/'synthetic-journal.jsonl';source.touch(mode=0o600)
    envfile=output/'empty.env';envfile.touch(mode=0o600)
    db=output/'simulation.sqlite';env=child_env(root,db)
    cmd=[sys.executable,str(cli),'--watch','--env-file',str(envfile),'--source',str(source),'--synthetic-fills']
    children=[];handles=[];steps=[]
    def note(name,ok,**extra):
        steps.append(dict(check=name,status='PASS' if ok else 'FAIL',**extra))
        print(('PASS: ' if ok else 'FAIL: ')+name,flush=True)
        if not ok:raise RuntimeError('CHECK_FAILED')
    def start(label):
        log=output/(label+'.log');handle=log.open('w');handles.append(handle)
        proc=subprocess.Popen(cmd,cwd=output,env=env,stdout=handle,stderr=subprocess.STDOUT,start_new_session=True)
        children.append(proc);return proc,log
    def stop(proc,sig):
        if proc.poll() is None:proc.send_signal(sig)
        try:return proc.wait(timeout=12)
        except subprocess.TimeoutExpired:
            proc.kill();proc.wait(timeout=5);raise RuntimeError('SHUTDOWN_TIMEOUT')
    def view():return service.status()
    append(source,['ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21'])
    try:
        first,log=start('worker-1')
        wait_for('first worker baseline',lambda:latest(log).get('status')=='BASELINED_WAIT_NEXT_FRESH_SIGNAL',first)
        store=j.Store(db);broker=j.SimBroker(store);service=j.Service(store,broker,worker_start=False)
        note('Real --watch starts paused and baselines existing entry',view()['control']['mode']=='PAUSED' and not broker.orders())
        wait_for('fresh healthy heartbeat',lambda:view()['bridge_health']['status']=='HEALTHY',first)
        note('Worker reports real PID',view()['bridge_health']['pid']==first.pid)
        old=view();second,secondlog=start('second-worker')
        rc=second.wait(timeout=12);new=view()
        note('Second worker rejected without replacing owner',rc==2 and latest(secondlog).get('reason')=='SIM_BRIDGE_WORKER_ALREADY_RUNNING'
             and new['bridge_health']['instance']==old['bridge_health']['instance'] and new['control']['version']==old['control']['version'])
        seq=append(source,['PATH1_ARMED_RSI_CROSS_EMA3_UP'])
        wait_for('appended candidate consumed',lambda:latest(log).get('source_sequence',0)>=seq,first)
        note('Candidate creates no order',not broker.orders())
        seq=append(source,['ENTRY_BEARISH_ROUTE_B_STRUCTURAL'])
        wait_for('appended paused entry consumed',lambda:latest(log).get('source_sequence',0)>=seq,first)
        with store.db() as d:events=[json.loads(x[0]) for x in d.execute('SELECT data FROM sim_bridge_events')]
        note('Confirmed entry while paused blocked and audited',bool(events) and all(x['state']=='BLOCKED' for x in events) and not broker.orders())
        lines=len(log.read_text().splitlines())
        wait_for('another background poll',lambda:len(log.read_text().splitlines())>lines,first)
        note('Repeated polls do not submit orders',not broker.orders())
        rc=stop(first,signal.SIGINT)
        note('Graceful SIGINT marks STOPPED and PAUSED',rc==130 and view()['bridge_health']['status']=='STOPPED' and view()['control']['mode']=='PAUSED')
        restarted,rlog=start('worker-restarted')
        wait_for('restart reads durable cursor',lambda:latest(rlog).get('status')=='SIMULATOR_SOURCE_PROCESSED',restarted)
        note('Restart stays paused and never replays history',view()['control']['mode']=='PAUSED' and not broker.orders()
             and view()['bridge_health']['pid']==restarted.pid)
        # Arm ONLY the isolated simulator, with no additional source entry appended.
        j.command(service,'reconcile');j.command(service,'resume')
        note('Explicit isolated Resume succeeds when healthy',view()['control']['mode']=='ARMED')
        stop(restarted,signal.SIGKILL)
        wait_for('SIGKILL heartbeat ages beyond limit',lambda:(view()['bridge_health'].get('heartbeat_age_seconds') or 0)>15,timeout=22)
        health=service.watch_bridge_health()
        note('Forced kill stale heartbeat blocks and watchdog pauses',health['status']=='HEARTBEAT_STALE' and view()['control']['mode']=='PAUSED')
        reason=None
        j.command(service,'reconcile')
        try:j.command(service,'resume')
        except j.Blocked as exc:reason=str(exc)
        note('Stale worker cannot be resumed',reason=='SIM_BRIDGE_HEARTBEAT_STALE',reason=reason)
        recovered,recoverylog=start('worker-after-kill')
        wait_for('kernel lock released and worker recovers',lambda:latest(recoverylog).get('bridge_health',{}).get('healthy') is True,recovered)
        note('Post-kill recovery does not auto-resume or replay BUY',view()['control']['mode']=='PAUSED' and not broker.orders())
        stop(recovered,signal.SIGINT)
        note('Final isolated worker stopped flat and paused',view()['bridge_health']['status']=='STOPPED'
             and view()['control']['mode']=='PAUSED' and not any(broker.positions().values()))
    except Exception as exc:
        steps.append(dict(check='Lifecycle runner completed',status='FAIL',error_type=type(exc).__name__,reason=str(exc)[:160]))
    finally:
        for proc in children:
            if proc.poll() is None:
                proc.kill();proc.wait(timeout=5)
        for handle in handles:handle.close()
    status='PASS' if steps and all(x['status']=='PASS' for x in steps) else 'FAIL'
    report=dict(status=status,checks=steps,evidence_mode='REAL_WATCH_SUBPROCESSES_WITH_SYNTHETIC_JOURNAL',
        production_execution_enabled=False,orders_sent_to_upstox=False,
        limitations=['NO_REAL_BROKER','NO_MARKET_SESSION_REQUIRED','NO_ENTRY_FILL_OR_EXIT_PERFORMANCE_TEST',
                     'WATCHDOG_METHOD_CALLED_BY_TEST_DRIVER_NOT_API_SCHEDULER','SINGLE_HOST_ONLY'])
    (output/'report.json').write_text(json.dumps(report,indent=2))
    text='# Isolated real --watch process validation\n\n| Check | Status |\n|---|---|\n'
    text+=''.join('| '+x['check']+' | '+x['status']+' |\n' for x in steps)
    text+='\nOverall: '+status+'\nNo production orders. Synthetic source; actual subprocesses and wall-clock heartbeat.\n'
    (output/'summary.md').write_text(text);print(text,flush=True);return 0 if status=='PASS' else 2

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();return run(a.output,Path.cwd().resolve())
if __name__=='__main__':
    try:raise SystemExit(main())
    except j.Blocked as exc:
        print(json.dumps(dict(status='BLOCKED',reason=str(exc),production_execution_enabled=False,orders_sent_to_upstox=False)));raise SystemExit(2)
