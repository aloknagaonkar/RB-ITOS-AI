"""Offline report. Synthetic INR, local fixture orders; no Upstox requests."""
import argparse,json
from pathlib import Path
from datetime import datetime,timedelta
from controller import Controller,Blocked

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    if a.output.exists():raise ValueError('USE_FRESH_OUTPUT_DIRECTORY')
    a.output.mkdir(parents=True,mode=0o700);clock=[datetime.fromisoformat('2026-10-26T09:24:59+05:30')]
    c=Controller(a.output/'controller.sqlite',session_date='2026-10-26',clock=lambda:clock[0]);rows=[]
    def note(label,ok):
        state=c.status();rows.append(dict(stage=label,status='PASS' if ok else 'FAIL',held_inr=f"{state['held_cents']/100:.2f}",control=state['control']['mode'],orders=len(state['fixture_orders'])))
        if not ok:raise AssertionError(label)
    c.funds('100000');v=c.resume('resume1',1)['version'];clock[0]+=timedelta(seconds=1)
    entry=c.entry('entry1',expected_version=v,signal_at=clock[0].isoformat())
    note('Reservation and intent durable before fixture order',c.status()['held_cents']==660000)
    c.venue.fill(entry['order_id'],20);c.reconcile();c.pause()
    sell=next(x for x in c.status()['plans'] if x['side']=='SELL')
    note('Partial entry Pause: cleanup pending, full hold retained',sell['quantity']==20 and c.status()['held_cents']==660000)
    c.venue.fill(sell['order_id'],20);c.reconcile()
    note('Terminal cleanup flat: hold released',c.status()['held_cents']==0)
    stale=False
    try:c.resume('stale',v)
    except Blocked:stale=True
    note('Stale Resume rejected',stale and c.status()['control']['mode']=='PAUSED')
    v=c.resume('resume2',c.status()['control']['version'])['version'];clock[0]+=timedelta(seconds=1)
    second=c.entry('entry2',expected_version=v,signal_at=clock[0].isoformat())
    c.venue.fill(second['order_id'],65);c.reconcile();c.pause();c.recover()
    note('Established position remains held after Pause and recovery',c.status()['held_cents']==660000)
    sell=c.exit('entry2');c.venue.fill(sell['order_id'],65,'105');c.reconcile();c.reconcile()
    note('Manual exit completes, allocation released once',c.status()['held_cents']==0)
    report=dict(status='PASS',stages=rows,controller=c.status(),production_execution_enabled=False,orders_sent_to_upstox=False)
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    text='# Durable offline controller\n\nSynthetic option prices/fills and cash. No application changes or broker requests.\n\n| Stage | Result | Control | Held INR | Fake orders |\n|---|---|---|---:|---:|\n'
    for r in rows:text+=f"| {r['stage']} | {r['status']} | {r['control']} | {r['held_inr']} | {r['orders']} |\n"
    text+='\nResult: PASS\nProduction execution enabled: false.\n';(a.output/'summary.md').write_text(text);print(text)
if __name__=='__main__':main()
