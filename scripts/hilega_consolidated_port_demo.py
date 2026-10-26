"""Consolidated closed-gate library: explicit offline single lifecycle demo."""
import argparse,json,os
from datetime import datetime,timedelta
from pathlib import Path
from market_lab.hilega_execution_port_v1.port import ClosedPort

def snapshot(p,sid,at,trades):
    orders=[];positions={}
    for o in p.adapter.transport.orders():
        orders.append(dict(order_id=o['order_id'],instrument=o['instrument'],product=o['product'],side=o['side'],quantity=o['quantity'],filled=o['filled'],pending=0 if o['status'] in {'FILLED','CANCELLED','REJECTED'} else o['quantity']-o['filled'],status=o['status']))
        k=(o['instrument'],o['product']);positions[k]=positions.get(k,0)+(o['filled'] if o['side']=='BUY' else -o['filled'])
    return dict(evidence_mode='OFFLINE_FIXTURE',account_scope=p.adapter.store.scope,snapshot_id=sid,observed_at=at.isoformat(),complete=True,orders=orders,trades=trades,positions=[dict(instrument=k[0],product=k[1],quantity=v) for k,v in positions.items()])
def trade(oid,side,qty,at,tid):return dict(order_id=oid,trade_id=tid,instrument='NSE_FO|12345',product='I',side=side,quantity=qty,price='100',filled_at=at.isoformat())
def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--output',required=True,type=Path);args=a.parse_args()
    if args.output.exists():raise ValueError('USE_NEW_OUTPUT_DIRECTORY')
    os.environ.update(HILEGA_PRODUCTION_WORKSPACE_MODE='SIMULATION_ONLY',HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED='0',HILEGA_PRODUCTION_BROKER_OBSERVE='0')
    args.output.mkdir(parents=True,mode=0o700);clock=[datetime.fromisoformat('2026-10-26T09:24:59+05:30')]
    p=ClosedPort(args.output/'fixture',mode='OFFLINE_FIXTURE',clock=lambda:clock[0]);rows=[]
    def note(stage,ok):
        s=p.status();rows.append(dict(stage=stage,status='PASS' if ok else 'FAIL',held=s['controller']['allocation']['held_total'],control=s['controller']['control']['mode']))
        if not ok:raise AssertionError(stage)
    p.fund_synthetic('100000');p.resume_next_fresh();clock[0]+=timedelta(seconds=1)
    contract=dict(instrument_key='NSE_FO|12345',underlying_key='NSE_INDEX|Nifty 50',instrument_type='CE',segment='NSE_FO',expiry='2026-10-27',lot_size=65,minimum_lot=65,freeze_quantity=1800)
    entry=p.enter(signal_id='consolidated-fresh',signal_at=clock[0].isoformat(),contract=contract);cid=entry['controller_id']
    note('Controller, reservation and adapter acknowledgement linked',p.status()['controller']['allocation']['held_total']=='6600.00')
    oid=p.adapter.status()['requests'][0]['order_id'];p.fixture_fill(cid,20);p.cancel_entry(cid)
    trades=[trade(oid,'BUY',20,clock[0],'t1')];r=p.reconcile_offline(snapshot(p,'partial',clock[0],trades))
    note('Partial cancellation remains 20 owned and held',r['reconciliation']['positions'][0]['remaining']==20)
    clock[0]+=timedelta(seconds=5);p.prepare_fixture_exit(cid,request_id='exit1',quantity=20,contract=contract);p.fixture_fill('exit1',20)
    sell=next(x['order_id'] for x in p.adapter.status()['requests'] if x['request_id']=='exit1');trades.append(trade(sell,'SELL',20,clock[0],'t2'))
    p.reconcile_offline(snapshot(p,'flat',clock[0],trades));release=p.release_offline(cid,snapshot_id='flat',request_id='release1')
    note('Verified flat proof releases controller hold once',release['release_applied'] and p.status()['release_consumer']['held_cents']==0)
    repeated=p.release_offline(cid,snapshot_id='flat',request_id='release1')
    note('Duplicate delivery returns original receipt',repeated['idempotent_replay'] and not repeated['release_applied'])
    recovered=ClosedPort.open(p.directory,clock=lambda:clock[0]);p=recovered
    note('Recovery stays paused without simulator fill fabrication',p.status()['controller']['control']['mode']=='PAUSED' and p.status()['simulator_fill_count']==0)
    clock[0]=datetime.fromisoformat('2026-10-26T09:24:59+05:30');closed=ClosedPort(args.output/'closed',mode='LIVE_CLOSED',clock=lambda:clock[0]);closed.fund_synthetic('100000');closed.resume_next_fresh();clock[0]+=timedelta(seconds=1)
    rejected=closed.enter(signal_id='closed-probe',signal_at=clock[0].isoformat(),contract=contract)
    if rejected['adapter_result']['status']!='PRODUCTION_MUTATIONS_CLOSED_IN_CODE':raise AssertionError('LIVE_GATE')
    report=dict(status='PASS',stages=rows,fixture=p.status(),closed=closed.status(),production_execution_enabled=False,orders_sent_to_upstox=False,active_workspace_modified=False)
    (args.output/'report.json').write_text(json.dumps(report,indent=2))
    text='# Consolidated execution port — closed gate\n\nExplicit offline cash, contracts, fills and positions. Existing application simulator route unchanged.\n\n| Stage | Result | Held INR | Control |\n|---|---|---:|---|\n'+''.join('| '+r['stage']+' | '+r['status']+' | '+r['held']+' | '+r['control']+' |\n' for r in rows)+'\nClosed HTTP gate: PASS\nResult: PASS\nProduction execution enabled: false.\n'
    (args.output/'summary.md').write_text(text);print(text)
if __name__=='__main__':main()
