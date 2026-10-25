"""Real allocation-aware --watch subprocesses, synthetic source/cash/fills only."""
import argparse,hashlib,json,os,signal,subprocess,sys,time
from datetime import datetime,timedelta
from pathlib import Path
import watch_support as w
j=w.j

def next_boundary(now):
    t=now.replace(second=0,microsecond=0)
    return t.replace(minute=t.minute-t.minute%5)+timedelta(minutes=5)

def append_event(path,names,entry_reference=None):
    import fcntl
    records=j.b.verified_records(path)
    at=datetime.now(j.IST).replace(second=0,microsecond=0)
    at=at.replace(minute=at.minute-at.minute%5);stamp=at.isoformat()
    row=dict(sequence=len(records)+1,previous_hash=records[-1]['record_hash'] if records else None,
        stage='DIRECTIONAL_DECISION',status='PROCESSED',payload=dict(policy_id=j.b.POLICY,strategy_version=j.b.VERSION,
        reconstructed=False,decision_timestamp=stamp,accepted_events=names,event_details=[dict(event_type=n,event_time=stamp,
        entry_time=entry_reference or stamp,qualified_signal_time=stamp) for n in names]))
    row['record_hash']=hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()
    with path.open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX);f.write(json.dumps(row)+'\n');f.flush();os.fsync(f.fileno())
    return row['sequence']

def run(output,root):
    j.installed();cli=root/'scripts/hilega_production_simulator_bridge.py'
    if hashlib.sha256(cli.read_bytes()).hexdigest()!=w.CLI_SHA:raise j.Blocked('WATCH_CLI_SOURCE_MISMATCH')
    if output.exists():raise j.Blocked('OUTPUT_EXISTS_USE_NEW_DIRECTORY')
    output.mkdir(parents=True,mode=0o700);output=output.resolve()
    source=output/'synthetic-journal.jsonl';source.touch(mode=0o600)
    envfile=output/'empty.env';envfile.touch(mode=0o600);db=output/'sim.sqlite'
    env=w.child_env(root,db);children=[];handles=[];checks=[];evidence={}
    command=[sys.executable,str(cli),'--watch','--env-file',str(envfile),'--source',str(source),'--synthetic-fills']
    def start(name,funded):
        log=output/(name+'.log');handle=log.open('w');handles.append(handle)
        proc=subprocess.Popen(command+(['--synthetic-cash','100000'] if funded else []),cwd=output,env=env,stdout=handle,stderr=subprocess.STDOUT,start_new_session=True)
        children.append(proc);return proc,log
    def stop(proc,sig=signal.SIGINT):
        if proc.poll() is None:proc.send_signal(sig)
        try:return proc.wait(timeout=12)
        except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5);raise RuntimeError('CHILD_STOP_TIMEOUT')
    def note(name,ok,**extra):
        checks.append(dict(check=name,status='PASS' if ok else 'FAIL',**extra));print(('PASS: ' if ok else 'FAIL: ')+name,flush=True)
        if not ok:raise RuntimeError('CHECK_FAILED_'+name.replace(' ','_'))
    def state():return service.status()
    def processed(log,seq,proc):w.wait_for('journal sequence '+str(seq),lambda:w.latest(log).get('source_sequence',0)>=seq,proc)
    append_event(source,['ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21'])
    try:
        proc,log=start('unfunded',False)
        w.wait_for('initial baseline',lambda:w.latest(log).get('status')=='BASELINED_WAIT_NEXT_FRESH_SIGNAL',proc)
        store=j.Store(db);broker=j.SimBroker(store);service=j.Service(store,broker,worker_start=False)
        w.wait_for('healthy source',lambda:state()['bridge_health']['healthy'],proc)
        j.command(service,'reconcile');reason=None
        try:j.command(service,'resume')
        except j.Blocked as exc:reason=str(exc)
        note('Unfunded real reader cannot Resume',reason=='SIM_ALLOCATION_SYNTHETIC_FUNDS_NOT_CONFIGURED' and not broker.orders(),reason=reason)
        stop(proc)
        proc,log=start('funded',True)
        w.wait_for('explicit synthetic funding',lambda:state()['allocation'].get('ready') is True and state()['bridge_health'].get('healthy') is True,proc)
        note('Funding never automatically arms',state()['control']['mode']=='PAUSED' and not broker.orders())
        # Verify background cash refresh, not just initial snapshot existence.
        time.sleep(1)
        w.wait_for('cash refresh across background poll',lambda:(state()['allocation'].get('funds_age_seconds') or 0)<1,proc,timeout=12)
        note('Synthetic cash refreshed by reader',state()['allocation']['synthetic_available_cash']=='100000')
        j.command(service,'reconcile');j.command(service,'resume')
        # Real CLI requires completed5m timestamps newer than Resume. Wait for a
        # genuine future boundary; do NOT backdate control state or patch clocks.
        target=next_boundary(datetime.now(j.IST));print('Waiting for fresh synthetic entry boundary '+target.isoformat()+' (up to5 minutes)',flush=True)
        deadline=time.monotonic()+320;last=0
        while datetime.now(j.IST)<target:
            if proc.poll() is not None:raise RuntimeError('READER_EXITED_WHILE_WAITING_FOR_BOUNDARY')
            if time.monotonic()>deadline:raise RuntimeError('BOUNDARY_WAIT_TIMEOUT')
            if time.monotonic()-last>=10:
                print('WAIT: next boundary in '+str(round((target-datetime.now(j.IST)).total_seconds()))+' seconds; reader running',flush=True);last=time.monotonic()
            time.sleep(.5)
        entry_seq=append_event(source,['ENTRY_BEARISH_ROUTE_B_STRUCTURAL']);processed(log,entry_seq,proc)
        w.wait_for('filled entry and central reservation',lambda:broker.positions().get('SIMULATOR|PE')==65 and state()['allocation'].get('held_total')=='6600.00',proc)
        note('Journal BUY holds central allocation',len([o for o in broker.orders() if o['side']=='BUY'])==1 and state()['allocation']['held_total']=='6600.00')
        evidence['after_entry']=state()
        # Pause after reader has reconciled fill; established position must remain.
        j.command(service,'reconcile');j.command(service,'pause')
        note('Pause preserves established position and reservation',broker.positions().get('SIMULATOR|PE')==65 and state()['allocation']['held_total']=='6600.00')
        entry_at=j.b.verified_records(source)[-1]['payload']['decision_timestamp']
        exit_seq=append_event(source,['STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21'],entry_at);processed(log,exit_seq,proc)
        w.wait_for('verified exit releases allocation',lambda:broker.positions().get('SIMULATOR|PE')==0 and state()['allocation']['held_total']=='0.00',proc)
        note('Paused journal EXIT sells then releases hold',len(broker.orders())==2 and state()['control']['mode']=='PAUSED')
        evidence['after_exit']=state();count=(len(broker.orders()),len(broker.fills()))
        lines=len(log.read_text().splitlines());w.wait_for('duplicate polling',lambda:len(log.read_text().splitlines())>lines,proc)
        note('Repeated reads do not repeat BUY or SELL',count==(len(broker.orders()),len(broker.fills())))
        rc=stop(proc);note('Funded reader graceful stop',rc==130 and state()['bridge_health']['status']=='STOPPED')
        # Restart without cash refresh; source heartbeat continues independently.
        proc,log=start('no-cash-refresh',False)
        w.wait_for('restart uses same cursor',lambda:w.latest(log).get('status')=='SIMULATOR_SOURCE_PROCESSED',proc)
        w.wait_for('cash expires while heartbeat remains healthy',lambda:state()['allocation']['status']=='FUNDS_STALE_OR_WRONG_SESSION',proc,timeout=40)
        note('Cash expiry independently blocks allocation',state()['bridge_health']['healthy'] and not state()['allocation']['ready'])
        j.command(service,'reconcile');reason=None
        try:j.command(service,'resume')
        except j.Blocked as exc:reason=str(exc)
        note('Stale cash Resume rejected',reason=='SIM_ALLOCATION_FUNDS_STALE_OR_WRONG_SESSION',reason=reason)
        stop(proc)
        proc,log=start('funded-recovery',True)
        w.wait_for('funding restored',lambda:state()['allocation']['ready'] and state()['bridge_health']['healthy'],proc)
        note('Cash recovery never auto-resumes',state()['control']['mode']=='PAUSED' and count==(len(broker.orders()),len(broker.fills())))
        j.command(service,'reconcile');j.command(service,'resume');stop(proc,signal.SIGKILL)
        w.wait_for('forced-kill heartbeat expiry',lambda:(state()['bridge_health'].get('heartbeat_age_seconds') or 0)>15,timeout=22)
        service.watch_bridge_health();note('Killed reader cannot leave entry permission active',state()['control']['mode']=='PAUSED' and state()['bridge_health']['status']=='HEARTBEAT_STALE')
        proc,log=start('final-recovery',True)
        w.wait_for('final process recovery',lambda:state()['bridge_health']['healthy'] and state()['allocation']['ready'],proc)
        note('Final restart retains released reservation and no duplicate order',state()['control']['mode']=='PAUSED' and state()['allocation']['held_total']=='0.00' and count==(len(broker.orders()),len(broker.fills())))
        stop(proc);evidence['final']=state()
    except Exception as exc:checks.append(dict(check='Integration completed',status='FAIL',error_type=type(exc).__name__,reason=str(exc)[:200]))
    finally:
        for proc in children:
            if proc.poll() is None:proc.kill();proc.wait(timeout=5)
        for handle in handles:handle.close()
    status='PASS' if checks and all(x['status']=='PASS' for x in checks) else 'FAIL'
    report=dict(status=status,checks=checks,evidence=evidence,production_execution_enabled=False,orders_sent_to_upstox=False,
        evidence_mode='REAL_WATCH_WITH_SYNTHETIC_JOURNAL_CASH_AND_FILLS',
        limitations=['NO_REAL_BROKER','SYNTHETIC_SAME_BOUNDARY_ENTRY_EXIT','WATCHDOG_DRIVER_CALL_NOT_API_SCHEDULER','ONE_LEG_ONLY'])
    (output/'report.json').write_text(json.dumps(report,indent=2))
    text='# Allocation-aware real --watch validation\n\n| Check | Status |\n|---|---|\n'+''.join('| '+x['check']+' | '+x['status']+' |\n' for x in checks)+'\nOverall: '+status+'\nNo Upstox orders; synthetic source/cash/prices/fills.\n'
    (output/'summary.md').write_text(text);print(text,flush=True);return 0 if status=='PASS' else 2

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();return run(a.output,Path.cwd().resolve())
if __name__=='__main__':
    try:raise SystemExit(main())
    except j.Blocked as exc:print(json.dumps(dict(status='BLOCKED',reason=str(exc),orders_sent_to_upstox=False)));raise SystemExit(2)
