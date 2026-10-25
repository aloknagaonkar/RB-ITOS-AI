"""Ownership link demonstration: offline executions only; assessment, no release."""
import argparse,json,os
from pathlib import Path
from support import dependencies,snapshot,fill,prepare_fixture_exit
from evidence import EvidenceLink
AT='2026-10-26T09:25:00+05:30';END='2026-10-26T09:25:05+05:30'
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    if a.output.exists():raise ValueError('USE_NEW_OUTPUT_DIRECTORY')
    os.environ.update(HILEGA_PRODUCTION_WORKSPACE_MODE='SIMULATION_ONLY',HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED='0',HILEGA_PRODUCTION_BROKER_OBSERVE='0')
    a.output.mkdir(parents=True,mode=0o700);f=dependencies();s,b,clock,link,entry,contract=f.build(a.output/'fixture')
    link.dispatch_prepared(entry['id'],contract,as_of=AT);proof=EvidenceLink(link,a.output/'fixture/evidence.sqlite');proof.register_entry(entry['id']);rows=[]
    def note(name,result):
        pos=result['reconciliation'].get('positions',[{}])[0]
        rows.append(dict(stage=name,ownership=result['reconciliation']['status'],remaining=pos.get('remaining'),assessment=result['assessment']['status'],held=s.status()['allocation']['held_total']))
    oid=link.adapter.status()['requests'][0]['order_id'];link.adapter.transport.fill(oid,20);link.adapter.cancel(entry['id'])
    trades=[fill(oid,'BUY',20,at=AT,trade_id='t1')]
    partial=proof.reconcile(snapshot(link.adapter,sid='partial',at=AT,trades=trades),as_of=AT);note('Cancelled entry with 20 filled',partial)
    prepare_fixture_exit(link,'exit1',20,at=END);proof.register_exit('exit1',entry['id'],as_of=END);link.adapter.submit('exit1')
    sell=next(x['order_id'] for x in link.adapter.status()['requests'] if x['request_id']=='exit1');link.adapter.transport.fill(sell,20)
    trades.append(fill(sell,'SELL',20,at=END,trade_id='t2'))
    final=proof.reconcile(snapshot(link.adapter,sid='flat',at=END,trades=trades),as_of=END);note('Bound exit fill and position flat',final)
    stale=proof.assess(as_of='2026-10-26T09:25:36+05:30')
    ok=partial['reconciliation'].get('positions',[{}])[0].get('remaining')==20 and final['assessment']['release_assessment_controller_ids']==[entry['id']] and not stale['release_assessment_controller_ids'] and not b.fills() and s.status()['allocation']['held_total']=='6600.00'
    report=dict(status='PASS' if ok else 'FAIL',stages=rows,partial=partial,final=final,stale_assessment=stale,controller=s.status(),ownership=proof.ledger.report(as_of=END),production_execution_enabled=False,controller_updated=False,orders_sent_to_upstox=False)
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    text='# Ownership evidence link\n\nExplicit offline order/trade/position evidence. Release assessment only; controller hold deliberately retained.\n\n| Stage | Ownership | Remaining | Assessment | Controller held INR |\n|---|---|---:|---|---:|\n'+''.join('| '+r['stage']+' | '+r['ownership']+' | '+str(r['remaining'])+' | '+r['assessment']+' | '+r['held']+' |\n' for r in rows)+'\nStale proof cannot assess release: '+str(not stale['release_assessment_controller_ids'])+'\nResult: '+report['status']+'\nProduction execution enabled: false.\n'
    (a.output/'summary.md').write_text(text);print(text);return 0 if ok else 2
if __name__=='__main__':raise SystemExit(main())
