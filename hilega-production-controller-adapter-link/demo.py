"""Installed controller -> held reservation -> closed/fixture broker adapter."""
import argparse,json,os
from pathlib import Path
from fixtures import build,AT

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    if a.output.exists():raise ValueError('USE_FRESH_OUTPUT_DIRECTORY')
    os.environ.update(HILEGA_PRODUCTION_WORKSPACE_MODE='SIMULATION_ONLY',HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED='0',HILEGA_PRODUCTION_BROKER_OBSERVE='0')
    a.output.mkdir(parents=True,mode=0o700);stages=[];evidence={}
    for name,closed in [('closed',True),('fixture',False)]:
        s,b,clock,link,entry,contract=build(a.output/name,closed=closed)
        before=s.status();result=link.dispatch_prepared(entry['id'],contract,as_of=AT);after=s.status()
        ok=before['allocation']['held_total']=='6600.00' and after['control']['mode']=='PAUSED' and not b.orders()
        if closed:ok=ok and result['adapter_result']['status']=='PRODUCTION_MUTATIONS_CLOSED_IN_CODE' and after['allocation']['held_total']=='0.00'
        else:ok=ok and result['adapter_result']['state']=='ACKNOWLEDGED_NOT_FILLED' and after['allocation']['held_total']=='6600.00'
        stages.append(dict(stage='Closed gate: known unsent, controller cancels/releases' if closed else 'Fixture acknowledgement: controller paused, reservation retained',status='PASS' if ok else 'FAIL',held=after['allocation']['held_total'],control=after['control']['mode']))
        if not closed:
            oid=link.adapter.status()['requests'][0]['order_id'];link.adapter.transport.fill(oid,20)
            link.cancel_fixture(entry['id']);link.adapter.reconcile_fixture()
            ok=s.status()['allocation']['held_total']=='6600.00' and not b.fills()
            stages.append(dict(stage='Partial fixture cancellation is not a controller flat proof',status='PASS' if ok else 'FAIL',held=s.status()['allocation']['held_total'],control=s.status()['control']['mode']))
        evidence[name]=dict(result=result,controller=s.status(),adapter=link.adapter.status())
    status='PASS' if all(r['status']=='PASS' for r in stages) else 'FAIL'
    report=dict(status=status,stages=stages,evidence=evidence,orders_sent_to_upstox=False,production_execution_enabled=False,application_runtime_modified=False)
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    text='# Installed controller and closed broker adapter link\n\nIsolated databases; synthetic cash, metadata and injected responses. Not an application rollout.\n\n| Stage | Result | Control | Held INR |\n|---|---|---|---:|\n'+''.join('| '+r['stage']+' | '+r['status']+' | '+r['control']+' | '+r['held']+' |\n' for r in stages)+'\nResult: '+status+'\nProduction execution enabled: false.\n'
    (a.output/'summary.md').write_text(text);print(text);return 0 if status=='PASS' else 2
if __name__=='__main__':raise SystemExit(main())
