"""Actual installed simulator service; synthetic cash, prices and fills only."""
import argparse,json,os
from datetime import datetime,timedelta
from pathlib import Path
import journal_support as j
from controller import Controller

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    j.installed()
    if a.output.exists():raise ValueError('USE_FRESH_OUTPUT_DIRECTORY')
    a.output.mkdir(parents=True,mode=0o700)
    os.environ['HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED']='0' # only this isolated demo process, never .env
    clock=[datetime.fromisoformat('2026-10-26T09:24:59+05:30')]
    store=j.Store(a.output/'simulation.sqlite');broker=j.SimBroker(store);s=j.Service(store,broker,lambda:clock[0])
    c=Controller(s,a.output/'allocation.sqlite');c.funds('cash1','100000');j.command(s,'reconcile');j.command(s,'resume')
    clock[0]+=timedelta(seconds=1);stages=[]
    plan=dict(instrument='SIMULATOR|CE',side='CE',offset=0,lot_size=65,lots=1,quantity=65,ask='100',buffer='100')
    def note(label):
        stages.append(dict(stage=label,held=c.ledger.status()['held_total'],control=s.status()['control']['mode'],
            remaining=sum(broker.positions().values()),orders=len(broker.orders())))
    row=c.submit(signal_id='bull1',signal_at=clock[0].isoformat(),snapshot_id='cash1',legs=[plan]);note('Reservation precedes simulator BUY')
    broker.fill(row['id'],20,'100');c.sync();note('Partial entry fill retains full hold')
    broker.fill(row['id'],65,'100');c.sync();note('Full entry fill retains hold for exposure')
    j.command(s,'pause');c.sync();note('Pause retains established position and hold')
    broker.auto_fill_sells=False;s.strategy_exit(position_id=row['id'],exit_id='sell1',price='100');c.sync();note('Pending exit retains hold')
    broker.fill('sell1',65,'100');c.sync();note('Verified completed exit releases hold')
    j.command(s,'reconcile');j.command(s,'resume');clock[0]+=timedelta(seconds=1)
    plan=dict(plan,instrument='SIMULATOR|PE',side='PE')
    broker.timeout_after_accept=True;broker.before_accept=lambda:setattr(broker,'unavailable',True)
    c.submit(signal_id='bear1',signal_at=clock[0].isoformat(),snapshot_id='cash1',legs=[plan])
    stages.append(dict(stage='Accepted timeout with unavailable evidence',held=c.ledger.status()['held_total'],control=s.status()['control']['mode'],remaining='UNKNOWN',orders='UNKNOWN'))
    broker.before_accept=None;broker.unavailable=False;c.sync();note('Reconciled zero-fill cancellation releases hold')
    ok=[x['held'] for x in stages]==['6600.00']*5+['0.00','6600.00','0.00'] and not any(broker.positions().values())
    report=dict(status='PASS' if ok else 'FAIL',stages=stages,allocation=c.ledger.status(),simulator=s.status(),
        simulated_orders=broker.orders(),simulated_fills=broker.fills(),orders_sent_to_upstox=False,production_execution_enabled=False)
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    text='# Isolated allocation → simulator lifecycle\n\nSynthetic cash/prices/fills. No Upstox requests.\n\n| Stage | Held INR | Control | Remaining quantity |\n|---|---:|---|---|\n'
    text+=''.join('| '+x['stage']+' | '+x['held']+' | '+x['control']+' | '+str(x['remaining'])+' |\n' for x in stages)
    text+='\nResult: '+report['status']+'\nIsolated single-leg integration; not installed into the running bridge.\n'
    (a.output/'summary.md').write_text(text);print(text);return 0 if ok else 2
if __name__=='__main__':raise SystemExit(main())
