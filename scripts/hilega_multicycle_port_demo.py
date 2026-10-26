"""Two offline broker lifecycles; explicit Resume, pending exit, recovery proof."""
import argparse,json,os
from datetime import datetime,timedelta
from pathlib import Path
from market_lab.hilega_execution_port_v1.port import ClosedPort
C1=dict(instrument_key='NSE_FO|12345',underlying_key='NSE_INDEX|Nifty 50',instrument_type='CE',segment='NSE_FO',expiry='2026-10-27',lot_size=65,minimum_lot=65,freeze_quantity=1800)
C2=dict(C1,instrument_key='NSE_FO|54321',instrument_type='PE')
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path);a=parser.parse_args()
    if a.output.exists():raise ValueError('USE_NEW_OUTPUT_DIRECTORY')
    os.environ.update(HILEGA_PRODUCTION_WORKSPACE_MODE='SIMULATION_ONLY',HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED='0',HILEGA_PRODUCTION_BROKER_OBSERVE='0')
    a.output.mkdir(parents=True,mode=0o700);clock=[datetime.fromisoformat('2026-10-26T09:24:59+05:30')]
    p=ClosedPort(a.output/'port',mode='OFFLINE_FIXTURE',clock=lambda:clock[0]);trades=[];rows=[]
    def note(name,ok):
        s=p.status();rows.append(dict(stage=name,status='PASS' if ok else 'FAIL',control=s['controller']['control']['mode'],held=s['controller']['allocation']['held_total'],orders=len(p.adapter.transport.orders()),releases=len(s['release_consumer']['receipts'])))
        if not ok:raise AssertionError(name)
    def fill(rid,quantity,tid):
        p.fixture_fill(rid,quantity);r=next(x for x in p.adapter.store.requests() if x['request_id']==rid);b=r['draft']['body']
        trades.append(dict(order_id=r['order_id'],trade_id=tid,instrument=b['instrument_token'],product=b['product'],side=b['transaction_type'],quantity=quantity,price='100',filled_at=clock[0].isoformat()))
    def snapshot(sid):
        orders=[];positions={}
        for o in p.adapter.transport.orders():
            orders.append(dict(order_id=o['order_id'],instrument=o['instrument'],product=o['product'],side=o['side'],quantity=o['quantity'],filled=o['filled'],pending=0 if o['status'] in {'FILLED','CANCELLED','REJECTED'} else o['quantity']-o['filled'],status=o['status']))
            k=(o['instrument'],o['product']);positions[k]=positions.get(k,0)+(o['filled'] if o['side']=='BUY' else -o['filled'])
        return dict(evidence_mode='OFFLINE_FIXTURE',account_scope=p.adapter.store.scope,snapshot_id=sid,observed_at=clock[0].isoformat(),complete=True,orders=orders,trades=list(trades),positions=[dict(instrument=k[0],product=k[1],quantity=v) for k,v in positions.items()])
    p.fund_synthetic('100000');p.resume_next_fresh();clock[0]+=timedelta(seconds=1)
    for n,c in [(1,C1),(2,C2)]:
        if n==2:p.resume_next_fresh();clock[0]+=timedelta(seconds=1)
        r=p.enter(signal_id='signal-'+str(n),signal_at=clock[0].isoformat(),contract=c);cid=r['controller_id']
        fill(cid,20,'buy-'+str(n));p.cancel_entry(cid);p.reconcile_offline(snapshot('partial-'+str(n)))
        clock[0]+=timedelta(seconds=2);p.prepare_fixture_exit(cid,request_id='exit-'+str(n),quantity=20,contract=c)
        if n==2:
            p.reconcile_offline(snapshot('pending-exit-2'));p.pause();blocked=False
            try:p.resume_next_fresh()
            except Exception:blocked=True
            note('Pending opposite-cycle exit and Pause block Resume',blocked and len(p.adapter.transport.orders())==4)
        fill('exit-'+str(n),20,'sell-'+str(n));p.reconcile_offline(snapshot('flat-'+str(n)));p.release_offline(cid,snapshot_id='flat-'+str(n),request_id='release-'+str(n))
        note('Cycle '+str(n)+' terminal flat releases only its hold',p.status()['release_consumer']['held_cents']==0 and p.status()['controller']['control']['mode']=='PAUSED')
    p=ClosedPort.open(p.directory,clock=lambda:clock[0]);blocked=False
    try:p.resume_next_fresh()
    except Exception:blocked=True
    note('Restart cannot Resume from historical release receipts',blocked and p.status()['controller']['control']['mode']=='PAUSED')
    clock[0]+=timedelta(seconds=1);p.reconcile_offline(snapshot('fresh-after-restart'))
    note('New ownership evidence does not automatically Resume',p.status()['controller']['control']['mode']=='PAUSED')
    p.resume_next_fresh();note('Explicit Resume accepts fresh flat projection',p.status()['controller']['control']['mode']=='ARMED')
    p.pause();note('Final state paused, two releases and no duplicate orders',len(p.status()['release_consumer']['receipts'])==2 and len(p.adapter.transport.orders())==4 and p.status()['controller']['control']['mode']=='PAUSED')
    report=dict(status='PASS',stages=rows,final=p.status(),production_execution_enabled=False,orders_sent_to_upstox=False,active_workspace_modified=False)
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    text='# Multi-cycle closed-gate execution port\n\nSynthetic cash/contracts/executions. Two fixture cycles; actual simulator route unchanged.\n\n| Stage | Result | Control | Held INR | Orders | Releases |\n|---|---|---|---:|---:|---:|\n'+''.join('| '+r['stage']+' | '+r['status']+' | '+r['control']+' | '+r['held']+' | '+str(r['orders'])+' | '+str(r['releases'])+' |\n' for r in rows)+'\nResult: PASS\nProduction execution enabled: false.\n'
    (a.output/'summary.md').write_text(text);print(text)
if __name__=='__main__':main()
