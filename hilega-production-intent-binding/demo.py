"""Offline draft -> durable acknowledgement -> existing fill ownership reconciliation."""
import argparse,json
from pathlib import Path
from registry import Registry
from provider_mapping import draft
SCOPE='OFFLINE_ACCOUNT';AT='2026-10-26T09:25:00+05:30';END='2026-10-26T09:30:00+05:30'
def req(rid,side,when):
    c=dict(instrument_key='NSE_FO|12345',underlying_key='NSE_INDEX|Nifty 50',instrument_type='CE',segment='NSE_FO',expiry='2026-10-27',lot_size=65,minimum_lot=65,freeze_quantity=1800)
    return draft(c,request_id=rid,side=side,lots=1,as_of=when)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise ValueError('USE_NEW_OUTPUT_DIRECTORY')
    a.output.mkdir(parents=True,mode=0o700);r=Registry(a.output/'registry.sqlite',SCOPE,'OFFLINE_FIXTURE');stages=[]
    def note(label,status,remaining=None):stages.append(dict(stage=label,status=status,remaining=remaining))
    r.prepare(req('entry1','BUY',AT),signal_id='signal1',signal_at=AT,direction='BULLISH');note('Intent persisted before receipt','OFFLINE_INTENT_REGISTERED')
    ack=lambda oid:dict(status='success',data=dict(order_ids=[oid]))
    r.bind_fixture_ack('entry1','receipt1',ack('OFFLINE-B1'),at=AT);note('Explicit fixture acknowledgement bound','OFFLINE_ACK_BOUND_NOT_FILLED')
    buy=dict(order_id='OFFLINE-B1',instrument='NSE_FO|12345',product='I',side='BUY',quantity=65,filled=65,pending=0,status='FILLED')
    fill=dict(order_id='OFFLINE-B1',trade_id='t1',instrument='NSE_FO|12345',product='I',side='BUY',quantity=65,price='100',filled_at=AT)
    s=dict(snapshot_id='snap1',observed_at=AT,account_scope=SCOPE,evidence_mode='OFFLINE_FIXTURE',complete=True,orders=[buy],trades=[fill],positions=[dict(instrument='NSE_FO|12345',product='I',quantity=65)])
    proof=r.reconcile_fixture(s,as_of=AT);note('Entry execution evidence reconciled',proof['status'],proof.get('positions',[{}])[0].get('remaining'))
    r=Registry(r.path,SCOPE,'OFFLINE_FIXTURE');note('Registry reopened with durable binding','PERSISTED',r.status(as_of=AT)['offline_ownership']['state'].get('positions',[{}])[0].get('remaining'))
    r.prepare(req('exit1','SELL',END),signal_id='exit-signal',signal_at=END,direction='BULLISH',parent_id='entry1')
    r.bind_fixture_ack('exit1','receipt2',ack('OFFLINE-E1'),at=END)
    sell=dict(buy,order_id='OFFLINE-E1',side='SELL');exitfill=dict(fill,order_id='OFFLINE-E1',trade_id='t2',side='SELL',price='105',filled_at=END)
    s.update(snapshot_id='snap2',observed_at=END,orders=[buy,sell],trades=[fill,exitfill],positions=[dict(instrument='NSE_FO|12345',product='I',quantity=0)])
    final=r.reconcile_fixture(s,as_of=END);note('Bound exit fills reconcile flat',final['status'],final.get('positions',[{}])[0].get('remaining'))
    repeated=r.reconcile_fixture(s,as_of=END);note('Duplicate evidence is idempotent',repeated['status'])
    ok=proof['status']=='RECONCILED_OFFLINE_FIXTURE' and final['status']=='RECONCILED_OFFLINE_FIXTURE' and final['positions'][0]['remaining']==0 and repeated['status']=='IDEMPOTENT_REPLAY'
    report=dict(status='PASS' if ok else 'FAIL',stages=stages,registry=r.status(as_of=END),production_execution_enabled=False,orders_sent=False)
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    text='# Durable intent and acknowledgement binding\n\nOffline fixtures; no Upstox calls or live ownership assertion.\n\n| Stage | Result | Remaining quantity |\n|---|---|---:|\n'+''.join('| '+x['stage']+' | '+x['status']+' | '+str(x['remaining'])+' |\n' for x in stages)+'\nResult: '+report['status']+'\nLive acknowledgement import and submission remain disabled.\n'
    (a.output/'summary.md').write_text(text);print(text);return 0 if ok else 2
if __name__=='__main__':raise SystemExit(main())
