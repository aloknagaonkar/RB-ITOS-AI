"""Offline fake transport lifecycle; no network, real balances or live orders."""
import argparse,json
from pathlib import Path
from datetime import datetime,timedelta
from adapter import Store,FakeTransport,Adapter,Blocked

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    if a.output.exists():raise Blocked('USE_FRESH_OUTPUT_DIRECTORY')
    a.output.mkdir(parents=True,mode=0o700);clock=[datetime.fromisoformat('2026-10-26T09:24:59+05:30')]
    store=Store(a.output/'fake-contract.sqlite');transport=FakeTransport(store,lambda:clock[0]);adapter=Adapter(store,transport,lambda:clock[0])
    adapter.resume();clock[0]+=timedelta(seconds=1);stages=[]
    def buy(key,instrument):return adapter.buy(key,instrument=instrument,quantity=65,limit_price='100',signal_at=clock[0].isoformat())
    def note(label):
        state=adapter.status();stages.append(dict(stage=label,control=state['control']['mode'],
            fake_buys=sum(o['side']=='BUY' for o in store.rows('fake_orders')),fake_sells=sum(o['side']=='SELL' for o in store.rows('fake_orders')),
            application_states=[r['status'] for r in state['intents']]))
    transport.timeout_after_accept=True;buy('first','FIXTURE|CE');note('Accepted response lost: UNKNOWN and paused')
    buy('first','FIXTURE|CE');note('Repeat same request: no second POST')
    adapter.reconcile();note('Read-only fake evidence binds original OPEN order')
    order=adapter.status()['intents'][0];transport.fill(order['order_id'],20,'100');adapter.reconcile()
    adapter.pause();note('Partial entry cancel and cleanup SELL: flat')
    adapter.resume();clock[0]+=timedelta(seconds=1);row=buy('second','FIXTURE|PE');transport.fill(row['order_id'],65,'100');adapter.reconcile()
    adapter.pause();note('Established filled position retained on Pause')
    adapter.resume();transport.auto_sell_fill=False;sell=adapter.exit('second',manual=False)
    blocked=False
    try:buy('blocked-opposite','FIXTURE|CE')
    except Blocked:blocked=True
    note('Pending SELL blocks opposite BUY')
    transport.fill(sell['order_id'],65,'100');adapter.reconcile();clock[0]+=timedelta(seconds=1)
    buy('fresh-opposite','FIXTURE|CE');note('SELL verified filled before fresh opposite BUY')
    adapter.pause();note('Final pending BUY cancelled; paused and flat')
    snapshot=transport.snapshot();ok=blocked and all(x['quantity']==0 for x in snapshot['positions']) and len(snapshot['orders'])==5
    report=dict(status='PASS' if ok else 'FAIL',stages=stages,adapter=adapter.status(),snapshot=snapshot,
        orders_sent_to_upstox=False,production_execution_enabled=False,evidence_mode='OFFLINE_FAKE_TRANSPORT')
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    text='# Offline order-adapter contract\n\nDurable synthetic requests and fake executions only. No Upstox API.\n\n| Stage | Control | Fake BUY orders | Fake SELL orders |\n|---|---|---:|---:|\n'
    text+=''.join('| '+x['stage']+' | '+x['control']+' | '+str(x['fake_buys'])+' | '+str(x['fake_sells'])+' |\n' for x in stages)
    text+='\nResult: '+report['status']+'\nProduction execution: false. No application changes.\n'
    (a.output/'summary.md').write_text(text);print(text);return 0 if ok else 2
if __name__=='__main__':raise SystemExit(main())
