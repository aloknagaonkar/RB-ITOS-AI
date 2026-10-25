"""Read-only recorded-journal transport validation into isolated simulator databases."""
import argparse, hashlib, inspect, json, os, uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from market_lab.hilega_production_foundation.core import Store, Service, SimBroker, Blocked, IST
from market_lab import hilega_production_simulator_bridge_v1 as b
from market_lab import hilega_production_bridge_health_v1 as h

def command(s, action):
    c=s.status()['control']
    return s.command(action,request_id=str(uuid.uuid4()),expected_version=c['version'],
                     session_date=c['session_date'],actor='ISOLATED_HISTORICAL_VALIDATION')

def installed():
    manifest=json.loads(Path(__file__).with_name('dependencies.json').read_text())
    from market_lab.hilega_combined_policy_v1 import POLICY_ID, VERSION
    if (POLICY_ID,VERSION)!=(b.POLICY,b.VERSION):raise Blocked('INSTALLED_POLICY_VERSION_MISMATCH')
    import market_lab.hilega_production_foundation.core as core
    import market_lab.hilega_production_ownership_v1 as ownership
    for module in (core,b,h,ownership):
        path=Path(inspect.getfile(module));expected=manifest[path.name]
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise Blocked('INSTALLED_DEPENDENCY_HASH_MISMATCH_'+path.name)

def select(records,day):
    out=[];last=None
    for r in records:
        if r.get('stage') not in {'DIRECTIONAL_DECISION','DIRECTIONAL_SESSION_CUTOFF'} or r.get('status')!='PROCESSED':continue
        p=r.get('payload') or {};value=p.get('decision_timestamp') or p.get('cutoff_timestamp')
        if value is None:continue
        at=b.aware(value).astimezone(IST)
        if at.date().isoformat()!=day:continue
        if p.get('policy_id')!=b.POLICY:continue
        if p.get('reconstructed') is True:continue
        if p.get('strategy_version')!=b.VERSION:raise Blocked('SELECTED_SESSION_VERSION_MISMATCH')
        events=b.accepted(r) # strict installed parser, no mutation/repair of source
        if last is not None and at<last:raise Blocked('SOURCE_DECISION_TIME_REGRESSION')
        last=at;out.append((r,at,events))
    if not out or not any(es for _,_,es in out):raise Blocked('NO_ELIGIBLE_EXECUTION_EVENTS_FOR_DATE')
    return out

def scenario(selected,output,mode):
    output.mkdir(mode=0o700)
    clock=[selected[0][1]-timedelta(seconds=1)]
    store=Store(output/'simulation.sqlite');broker=SimBroker(store)
    s=Service(store,broker,lambda:clock[0]);rows=[];checks=[];resume_next=False
    with h.worker_lock(store.path):
        run=h.claim(s);bridge=b.Bridge(s,output/'ownership-fixture.sqlite',auto_fill_entries=True,run_id=run)
        # Synthetic pre-roll health permits a controlled operator resume BEFORE first source boundary.
        # It is never presented as recorded feed/process health.
        h.heartbeat(s,run,source_at=clock[0].isoformat());command(s,'reconcile')
        if mode=='ARMED':command(s,'resume')
        for record,at,events in selected:
            clock[0]=at;h.heartbeat(s,run,source_at=at.isoformat())
            bridge.poll();before_orders=len(broker.orders());before_fills=len(broker.fills())
            bridge.process(record);proof=bridge.poll()
            orders=broker.orders();fills=broker.fills();new=orders[before_orders:];newfills=fills[before_fills:]
            count=(len(orders),len(fills));bridge.process(record);bridge.poll()
            duplicate_ok=count==(len(broker.orders()),len(broker.fills()))
            checks.append(duplicate_ok and proof['status']=='RECONCILED_OFFLINE_FIXTURE')
            # No second open simulator direction; all executed quantities remain nonnegative.
            checks.append(sum(q>0 for q in broker.positions().values())<=1 and all(q>=0 for q in broker.positions().values()))
            # Each reversal must close existing quantity before any opposite BUY fill.
            running={}
            for f in fills:
                if f['side']=='BUY':checks.append(not any(running.values()))
                running[f['instrument']]=running.get(f['instrument'],0)+(f['quantity'] if f['side']=='BUY' else -f['quantity'])
                checks.append(running[f['instrument']]>=0)
            if mode=='PAUSED':checks.append(not any(o['side']=='BUY' for o in orders))
            erows={x['id']:x for x in bridge.rows()}
            for e in events:
                v=erows[e['id']]
                rows.append(dict(source_sequence=record['sequence'],time=at.isoformat(),role=e['role'],direction=e['direction'],
                    source_event=e['source_event'],entry_reference=e.get('entry_reference_at'),qualified_at=e.get('qualified_at'),
                    exit_reason=e.get('exit_reason'),state=v['state'],reason=v.get('reason'),control=s.status()['control']['mode'],
                    new_buy_orders=sum(o['side']=='BUY' for o in new),new_sell_orders=sum(o['side']=='SELL' for o in new),
                    fill_order=[f['side'] for f in newfills],positions=broker.positions(),duplicate_idempotent=duplicate_ok))
            if mode=='RESUME_AFTER_FIRST_BLOCKED_ENTRY' and not resume_next and any(e['role']=='ENTRY' for e in events):
                checks.append(not any(o['side']=='BUY' for o in orders))
                clock[0]=at+timedelta(seconds=1);h.heartbeat(s,run,source_at=at.isoformat())
                command(s,'reconcile');command(s,'resume');resume_next=True
                n=len(broker.orders());bridge.process(record);bridge.poll()
                checks.append(n==len(broker.orders())) # consumed signal never enters on resume
        final_before_stop=s.status();h.finish(s,run)
        checks.append(s.status()['control']['mode']=='PAUSED')
    result=dict(status='PASS' if all(checks) else 'FAIL',scenario=mode,checks=len(checks),events=rows,
        simulated_orders=broker.orders(),simulated_fills=broker.fills(),final_positions=broker.positions(),
        control_before_stop=final_before_stop,control_after_stop=s.status(),bridge_events=bridge.rows(),
        source_entry_count=sum(e['role']=='ENTRY' for _,_,es in selected for e in es),
        source_exit_count=sum(e['role']=='EXIT' for _,_,es in selected for e in es),
        synthetic_heartbeat=True,synthetic_option_price=100,synthetic_quantity=65,
        performance_evaluated=False,production_execution_enabled=False,orders_sent_to_upstox=False)
    (output/'report.json').write_text(json.dumps(result,indent=2))
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,default=Path('data/live-observation/hilega-directional-v1/step-audit.jsonl'))
    p.add_argument('--date',required=True,type=date.fromisoformat);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();installed()
    # No dotenv, broker credentials, app controls, active DB path or network client is loaded.
    records=b.verified_records(a.source);selected=select(records,a.date.isoformat())
    if a.output.exists():raise Blocked('OUTPUT_EXISTS_USE_FRESH_DIRECTORY')
    a.output.mkdir(parents=True,mode=0o700)
    results=[scenario(selected,a.output/m,m) for m in ('ARMED','PAUSED','RESUME_AFTER_FIRST_BLOCKED_ENTRY')]
    entry_times={b.aware(e['event_at']).astimezone(IST).isoformat() for _,_,es in selected for e in es if e['role']=='ENTRY'}
    orphan_refs=[e.get('entry_reference_at') for _,_,es in selected for e in es if e['role']=='EXIT' and
                 (not e.get('entry_reference_at') or b.aware(e['entry_reference_at']).astimezone(IST).isoformat() not in entry_times)]
    count_entries=sum(e['role']=='ENTRY' for _,_,es in selected for e in es)
    armed_entries=[x for x in results[0]['bridge_events'] if x['role']=='ENTRY']
    parity=(not orphan_refs and len(armed_entries)==count_entries and all(x['state']=='SUBMITTED' for x in armed_entries)
        and all(x['state']=='EXIT_FINISHED' and x.get('reason')!='NO_OPEN_SIMULATOR_POSITION' for x in results[0]['bridge_events'] if x['role']=='EXIT'))
    # Partial journal coverage is NOT proof of full-session strategy parity.
    status='PASS' if all(r['status']=='PASS' for r in results) and parity else 'REVIEW_REQUIRED'
    report=dict(status=status,session_date=a.date.isoformat(),verified_snapshot_digest=hashlib.sha256(json.dumps(records,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        source_chain_tip=records[-1]['record_hash'] if records else None,selected_decision_records=len(selected),
        first_boundary=selected[0][1].isoformat(),last_boundary=selected[-1][1].isoformat(),
        recorded_event_dispatch_parity='PASS' if parity else 'REVIEW_REQUIRED',unmatched_exit_entry_references=orphan_refs,
        full_session_coverage='NOT_ESTABLISHED_BY_THIS_RUNNER',strategy_indicator_replay='NOT_PERFORMED',
        evidence_mode='RECORDED_STRATEGY_EVENTS_WITH_SYNTHETIC_SIMULATOR_EXECUTION',
        production_execution_enabled=False,orders_sent_to_upstox=False,scenarios=[dict(scenario=r['scenario'],status=r['status']) for r in results])
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    lines=['# Recorded strategy journal → isolated simulator validation','',
        'Recorded events unchanged. Synthetic option prices, fills, heartbeat and operator timing. No P&L validation.',
        'Full-session coverage and indicator parity are not established. Any unmatched lifecycle needs review.','',
        '| Scenario | Source time IST | Direction | Event | Result | Reason | New BUY / SELL |',
        '|---|---|---|---|---|---|---|']
    for r in results:
        for x in r['events']:
            lines.append('| '+' | '.join(str(v).replace('|','/') for v in (r['scenario'],x['time'],x['direction'],x['role'],x['state'],x['reason'],str(x['new_buy_orders'])+' / '+str(x['new_sell_orders'])))+' |')
    lines+=['','Overall: '+status,'Recorded-event dispatch parity: '+report['recorded_event_dispatch_parity'],
            'Full source event names, qualification times, exit references, orders and fills: scenario report.json files.']
    text='\n'.join(lines)+'\n';(a.output/'summary.md').write_text(text);print(text)
    return 0 if status=='PASS' else 2
if __name__=='__main__':
    try:raise SystemExit(main())
    except (Blocked,h.HealthBlocked) as exc:
        print(json.dumps(dict(status='BLOCKED',reason=str(exc),production_execution_enabled=False,orders_sent_to_upstox=False)));raise SystemExit(2)
