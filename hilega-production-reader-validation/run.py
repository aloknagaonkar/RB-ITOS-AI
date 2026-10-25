"""Controlled historical prefix replay through installed journal-reader iterations."""
import argparse,hashlib,json,os
from datetime import date,timedelta
from pathlib import Path
import journal_support as j
b,h=j.b,j.h
Blocked=j.Blocked

def write_prefix(path,records):
    # Original records/hashes unchanged. Only the isolated copy is written.
    with path.open('w',encoding='utf-8') as f:
        for r in records:f.write(json.dumps(r,ensure_ascii=False)+'\n')
    path.chmod(0o600)

def cursor(store):
    with store.db() as d:
        row=d.execute('SELECT data FROM sim_bridge_source WHERE id=1').fetchone()
    return json.loads(row[0]) if row else None

def counts(broker):return (len(broker.orders()),len(broker.fills()))

def exercise(records,selected,out,mode):
    out.mkdir(mode=0o700);source=out/'journal-copy.jsonl'
    first=selected[0];clock=[first[1]-timedelta(seconds=1)]
    store=j.Store(out/'simulation.sqlite');broker=j.SimBroker(store)
    s=j.Service(store,broker,lambda:clock[0]);steps=[];events=[];did_resume=False;did_fault=False
    def check(name,ok,**details):
        steps.append(dict(check=name,status='PASS' if ok else 'FAIL',**details))
    with h.worker_lock(store.path):
        run=h.claim(s);bridge=b.Bridge(s,out/'ownership.sqlite',auto_fill_entries=True,run_id=run)
        prefix=first[0]['sequence']-1
        write_prefix(source,records[:prefix]);r=bridge.run_source_once(source)
        check('Initial baseline never buys',r['status']=='BASELINED_WAIT_NEXT_FRESH_SIGNAL' and not broker.orders())
        check('Baseline cursor preserved',cursor(store)['sequence']==prefix)
        h.heartbeat(s,run,source_at=clock[0].isoformat());j.command(s,'reconcile')
        if mode=='ARMED':j.command(s,'resume')
        for record,at,accepted in selected:
            clock[0]=at
            # Controlled fresh health at each historical poll; not measured live-feed health.
            h.heartbeat(s,run,source_at=at.isoformat());bridge.poll()
            end=record['sequence'];write_prefix(source,records[:end]);before=counts(broker)
            result=bridge.run_source_once(source);proof=bridge.poll();after=counts(broker)
            check('Reader advances original cursor',cursor(store)['sequence']==end,sequence=end)
            names=record['payload'].get('accepted_events',[])
            if any(n in b.ARMS for n in names) and not accepted:
                check('Recorded candidate alone never buys',counts(broker)==before,sequence=end)
            check('Ownership reconciles',proof['status']=='RECONCILED_OFFLINE_FIXTURE',sequence=end)
            for _ in range(2):bridge.run_source_once(source)
            check('Repeated journal polls do not duplicate',counts(broker)==after,sequence=end)
            for e in accepted:
                row=next(x for x in bridge.rows() if x['id']==e['id'])
                events.append(dict(sequence=end,time=at.isoformat(),direction=e['direction'],role=e['role'],
                    event=e['source_event'],state=row['state'],reason=row.get('reason'),
                    control=s.status()['control']['mode'],new_orders=after[0]-before[0]))
            if mode=='PAUSED_THEN_RESUME' and not did_resume and any(e['role']=='ENTRY' for e in accepted):
                check('Paused confirmed entry blocked',not broker.orders())
                clock[0]=at+timedelta(seconds=1);h.heartbeat(s,run,source_at=at.isoformat())
                j.command(s,'reconcile');j.command(s,'resume');before=counts(broker)
                bridge.run_source_once(source)
                check('Resume cannot replay consumed entry',counts(broker)==before)
                did_resume=True
            if mode=='PAUSED_THEN_RESUME' and not did_fault and any(broker.positions().values()):
                held=broker.positions();clock[0]=at+timedelta(seconds=16)
                state=s.watch_bridge_health()
                check('Lost heartbeat pauses without browser',state['status']=='HEARTBEAT_STALE' and s.status()['control']['mode']=='PAUSED')
                check('Established position retained',broker.positions()==held)
                h.heartbeat(s,run,source_at=at.isoformat());bridge.poll()
                check('Heartbeat recovery does not auto-resume',s.status()['control']['mode']=='PAUSED')
                did_fault=True
        final_positions=broker.positions();before=counts(broker);saved=cursor(store)
        h.finish(s,run)
        # Reconstruct Service/Bridge against the SAME isolated DB and journal cursor.
        # This exercises durable restart state, not a real subprocess/OS crash.
        s=j.Service(store,broker,lambda:clock[0]);run=h.claim(s)
        bridge=b.Bridge(s,out/'ownership.sqlite',auto_fill_entries=True,run_id=run)
        h.heartbeat(s,run,source_at=clock[0].isoformat())
        bridge.run_source_once(source);bridge.poll()
        check('Restart remains paused',s.status()['control']['mode']=='PAUSED')
        check('Restart preserves cursor and never replays BUY',cursor(store)==saved and counts(broker)==before)
        # Fresh heartbeat cannot conceal stale source, and Resume is rejected.
        clock[0]+=timedelta(seconds=391);h.heartbeat(s,run,source_at=(clock[0]-timedelta(seconds=391)).isoformat())
        j.command(s,'reconcile');reason=None
        try:j.command(s,'resume')
        except Blocked as exc:reason=str(exc)
        check('Stale source blocks Resume',reason=='SIM_BRIDGE_SOURCE_STALE_OR_FUTURE',reason=reason)
        # Truncate ONLY test journal. Then restore original prefix and corrupt one field.
        write_prefix(source,[]);reason=None
        try:bridge.run_source_once(source)
        except Blocked as exc:reason=str(exc)
        check('Truncation blocks and pauses',reason=='SOURCE_CHANGED_OR_TRUNCATED' and s.status()['control']['mode']=='PAUSED',reason=reason)
        prefix_records=records[:selected[-1][0]['sequence']]
        write_prefix(source,prefix_records)
        altered=json.loads(json.dumps(prefix_records));altered[-1]['reader_validation_tamper']=True
        write_prefix(source,altered);reason=None
        try:bridge.run_source_once(source)
        except Blocked as exc:reason=str(exc)
        check('Tampered chain rejected',reason=='SOURCE_CHAIN_INVALID',reason=reason)
        check('Faults never create orders',counts(broker)==before)
        write_prefix(source,prefix_records);h.finish(s,run)
    entries=[x for x in bridge.rows() if x['role']=='ENTRY']
    if mode=='ARMED':
        check('Armed confirmed entries submitted',bool(entries) and all(x['state']=='SUBMITTED' for x in entries))
        check('Armed exits match owned entries',all(x['state']=='EXIT_FINISHED' and x.get('reason')=='FLAT_CONFIRMED' for x in bridge.rows() if x['role']=='EXIT'))
    if mode=='PAUSED_THEN_RESUME':
        check('Resume and heartbeat fault paths exercised',did_resume and did_fault)
        check('Exit still closes after health pause',not any(final_positions.values()))
    check('No simultaneous opposite exposure',sum(q>0 for q in final_positions.values())<=1 and all(q>=0 for q in final_positions.values()))
    report=dict(status='PASS' if all(x['status']=='PASS' for x in steps) else 'REVIEW_REQUIRED',scenario=mode,
        checks=steps,events=events,simulated_orders=broker.orders(),simulated_fills=broker.fills(),
        final_positions=final_positions,final_control=s.status(),cursor=cursor(store),
        synthetic_prices_fills_clock_and_heartbeats=True,production_execution_enabled=False,orders_sent_to_upstox=False)
    (out/'report.json').write_text(json.dumps(report,indent=2));return report

def baseline_history(records,selected,out):
    out.mkdir(mode=0o700);source=out/'journal-copy.jsonl'
    write_prefix(source,records[:selected[-1][0]['sequence']])
    clock=lambda:selected[-1][1]
    store=j.Store(out/'simulation.sqlite');broker=j.SimBroker(store);service=j.Service(store,broker,clock)
    with h.worker_lock(store.path):
        run=h.claim(service);bridge=b.Bridge(service,out/'ownership.sqlite',auto_fill_entries=True,run_id=run)
        result=bridge.run_source_once(source);bridge.run_source_once(source)
        ok=result['status']=='BASELINED_WAIT_NEXT_FRESH_SIGNAL' and not broker.orders() and not bridge.rows()
        h.finish(service,run)
    report=dict(scenario='EXISTING_HISTORY_BASELINE',status='PASS' if ok else 'FAIL',
        checks=[dict(check='Existing entries/exits are baselined, never executed',status='PASS' if ok else 'FAIL')],
        events=[],cursor=cursor(store),production_execution_enabled=False,orders_sent_to_upstox=False)
    (out/'report.json').write_text(json.dumps(report,indent=2));return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,default=Path('data/live-observation/hilega-directional-v1/step-audit.jsonl'))
    p.add_argument('--date',required=True,type=date.fromisoformat);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();j.installed();records=b.verified_records(a.source);selected=j.select(records,a.date.isoformat())
    # Never allow outputs inside an existing app directory or reuse a previous DB.
    if a.output.exists():raise Blocked('OUTPUT_EXISTS_USE_FRESH_DIRECTORY')
    a.output.mkdir(parents=True,mode=0o700)
    results=[baseline_history(records,selected,a.output/'EXISTING_HISTORY_BASELINE')]
    results += [exercise(records,selected,a.output/m,m) for m in ('ARMED','PAUSED_THEN_RESUME')]
    status='PASS' if all(r['status']=='PASS' for r in results) else 'REVIEW_REQUIRED'
    report=dict(status=status,session_date=a.date.isoformat(),source_chain_tip=records[-1]['record_hash'],
        source_snapshot_digest=hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest(),
        selected_records=len(selected),scenarios=[dict(scenario=r['scenario'],status=r['status']) for r in results],
        limitations=['SYNTHETIC_EXECUTION_AND_CLOCK','NO_INDICATOR_OR_PNL_REPLAY','NO_FULL_SESSION_COVERAGE_PROOF',
        'READER_ITERATIONS_NOT_WATCH_SUBPROCESS','NO_BROWSER_OR_API_TEST','NO_REAL_BROKER'],
        production_execution_enabled=False,orders_sent_to_upstox=False)
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    lines=['# Isolated journal-reader validation','',
        'Original hash-chained record prefixes; synthetic fills, health and clock. No Upstox orders.','',
        '| Scenario | Check | Status |','|---|---|---|']
    for r in results:
        lines+=['| '+r['scenario']+' | '+x['check']+' | '+x['status']+' |' for x in r['checks']]
    lines+=['','| Scenario | Time IST | Direction | Event | Result | Reason |','|---|---|---|---|---|---|']
    for r in results:
        lines+=['| '+' | '.join(str(v).replace('|','/') for v in (r['scenario'],x['time'],x['direction'],x['role'],x['state'],x['reason']))+' |' for x in r['events']]
    lines+=['','Overall: '+status,'See scenario report.json for cursor, controls, orders/fills and check details.']
    text='\n'.join(lines)+'\n';(a.output/'summary.md').write_text(text);print(text)
    return 0 if status=='PASS' else 2
if __name__=='__main__':
    try:raise SystemExit(main())
    except (Blocked,h.HealthBlocked) as exc:
        print(json.dumps(dict(status='BLOCKED',reason=str(exc),production_execution_enabled=False,orders_sent_to_upstox=False)));raise SystemExit(2)
