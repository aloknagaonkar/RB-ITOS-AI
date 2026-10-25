"""Synthetic heartbeat/control lifecycle demonstration. No broker requests."""
import argparse,json,uuid
from datetime import datetime,timedelta
from pathlib import Path
from market_lab.hilega_production_foundation.core import Store,Service,SimBroker
from market_lab.hilega_production_simulator_bridge_v1 import Bridge,POLICY,VERSION
from market_lab.hilega_production_bridge_health_v1 import claim,heartbeat,finish

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise SystemExit('OUTPUT_EXISTS_USE_NEW_DIRECTORY')
    a.output.mkdir(parents=True,mode=0o700)
    clock=[datetime.fromisoformat('2026-10-25T09:24:59+05:30')]
    store=Store(a.output/'sim.sqlite');s=Service(store,SimBroker(store),lambda:clock[0])
    run=claim(s);bridge=Bridge(s,a.output/'ownership-fixture.sqlite',auto_fill_entries=True,run_id=run);rows=[]
    def cmd(action,**kw):
        c=s.status()['control'];return s.command(action,request_id=str(uuid.uuid4()),expected_version=c['version'],session_date=c['session_date'],actor='synthetic-health-demo',**kw)
    def note(label):
        state=s.status();rows.append(dict(stage=label,control=state['control']['mode'],health=state['bridge_health']['status'],remaining=state['ledger_remaining_quantity']))
    def event(name):
        at=clock[0].isoformat()
        return dict(stage='DIRECTIONAL_DECISION',status='PROCESSED',payload=dict(policy_id=POLICY,strategy_version=VERSION,
            reconstructed=False,decision_timestamp=at,accepted_events=[name],event_details=[dict(event_type=name,event_time=at,entry_time=at)]))
    note('Lease claimed: entries paused')
    heartbeat(s,run,source_at=clock[0].isoformat());note('Healthy source: still paused')
    cmd('reconcile');cmd('resume');clock[0]=datetime.fromisoformat('2026-10-25T09:25:00+05:30')
    heartbeat(s,run,source_at=clock[0].isoformat());bridge.process(event('ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21'));note('Explicit resume and confirmed synthetic entry')
    clock[0]+=timedelta(seconds=16);s.watch_bridge_health();note('Heartbeat lost: paused, established position held')
    heartbeat(s,run,source_at=clock[0].isoformat());note('Heartbeat recovered: no automatic resume')
    entry=next(i for i in s.store.intents() if i['side']=='BUY');cmd('exit',position_id=entry['id']);bridge.poll();note('Manual simulator exit remains available')
    cmd('reconcile');cmd('resume');clock[0]=datetime.fromisoformat('2026-10-25T09:30:00+05:30')
    heartbeat(s,run,source_at=clock[0].isoformat());bridge.process(event('ENTRY_BEARISH_ROUTE_B_STRUCTURAL'));note('Explicit resume: next fresh synthetic signal')
    finish(s,run);note('Worker stopped: paused, entries blocked')
    entry=next(i for i in s.store.intents() if i['side']=='BUY' and s._remaining(i)[0]);cmd('exit',position_id=entry['id']);bridge.poll();note('Exit after stop: flat and paused')
    ok=(rows[0]['health']=='STARTING' and rows[1]['control']=='PAUSED' and rows[2]['remaining']==65 and
        rows[3]['health']=='HEARTBEAT_STALE' and rows[3]['control']=='PAUSED' and rows[3]['remaining']==65 and
        rows[4]['health']=='HEALTHY' and rows[4]['control']=='PAUSED' and rows[5]['remaining']==0 and
        rows[6]['remaining']==65 and rows[7]['health']=='STOPPED' and rows[8]['remaining']==0)
    report=dict(status='PASS' if ok else 'FAIL',stages=rows,control=s.status(),events=s.store.events(),
                ownership=bridge.ledger.report(as_of=s.now().isoformat()),production_execution_enabled=False,orders_sent_to_upstox=False)
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    lines=['# Simulator bridge health — synthetic demonstration','',
        'No live broker requests, market replay or production orders.','',
        '| Stage | Control | Health | Simulated remaining quantity |','|---|---|---|---:|']
    lines+=['| '+r['stage']+' | '+r['control']+' | '+r['health']+' | '+str(r['remaining'])+' |' for r in rows]
    lines+=['','Result: '+report['status'],'Production execution enabled: false']
    text='\n'.join(lines)+'\n';(a.output/'summary.md').write_text(text);print(text);raise SystemExit(0 if ok else 1)
if __name__=='__main__':main()
