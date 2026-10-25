"""Offline release commit, retry and interrupted-transaction demonstration."""
import argparse,json,os
from pathlib import Path
from support import build_flat,build_partial,consume,END

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    if a.output.exists():raise ValueError('USE_FRESH_OUTPUT_DIRECTORY')
    os.environ.update(HILEGA_PRODUCTION_WORKSPACE_MODE='SIMULATION_ONLY',HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED='0',HILEGA_PRODUCTION_BROKER_OBSERVE='0')
    a.output.mkdir(parents=True,mode=0o700);rows=[];evidence={}
    def note(name,env,ok):
        state=env['consumer'].status();rows.append(dict(stage=name,status='PASS' if ok else 'FAIL',held_inr=f"{state['held_cents']/100:.2f}",receipts=len(state['receipts']),control=env['service'].status()['control']['mode']))
        if not ok:raise AssertionError(name)
    partial=build_partial(a.output/'partial');blocked=False
    try:consume(partial,as_of='2026-10-26T09:25:00+05:30')
    except Exception:blocked=True
    note('Partial cancelled entry: release rejected',partial,blocked and partial['consumer'].status()['held_cents']==660000)
    flat=build_flat(a.output/'flat');first=consume(flat)
    note('Verified terminal flat: release and receipt committed',flat,first['release_applied'] and flat['consumer'].status()['held_cents']==0)
    repeated=consume(flat)
    note('Duplicate delivery: no second release',flat,repeated['idempotent_replay'] and not repeated['release_applied'] and len(flat['consumer'].status()['receipts'])==1)
    stale=build_flat(a.output/'stale');blocked=False
    try:consume(stale,as_of='2026-10-26T09:25:36+05:30')
    except Exception:blocked=True
    note('Stale first proof: hold retained',stale,blocked and stale['consumer'].status()['held_cents']==660000)
    rollback=build_flat(a.output/'rollback')
    class Stop(BaseException):pass
    def fail(point):
        if point=='AFTER_HOLD_UPDATE_BEFORE_RECEIPT':raise Stop()
    rollback['consumer'].checkpoint=fail
    try:consume(rollback)
    except Stop:pass
    state=rollback['consumer'].status()
    note('Interrupted release: hold/receipt transaction rolled back',rollback,state['held_cents']==660000 and not state['receipts'])
    rollback['consumer'].checkpoint=lambda p:None;consume(rollback)
    note('Recovery consumes proof once and remains paused',rollback,rollback['consumer'].status()['held_cents']==0 and rollback['service'].status()['control']['mode']=='PAUSED')
    for name,env in [('partial',partial),('flat',flat),('stale',stale),('rollback',rollback)]:
        evidence[name]=dict(consumer=env['consumer'].status(),controller=env['service'].status(),simulator_fill_count=len(env['broker'].fills()))
    report=dict(status='PASS',stages=rows,evidence=evidence,production_execution_enabled=False,orders_sent_to_upstox=False,application_runtime_modified=False)
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    text='# Ownership release consumer\n\nIsolated synthetic reservations and offline ownership proof; no active application writes.\n\n| Stage | Result | Held INR | Release receipts | Control |\n|---|---|---:|---:|---|\n'+''.join('| '+r['stage']+' | '+r['status']+' | '+r['held_inr']+' | '+str(r['receipts'])+' | '+r['control']+' |\n' for r in rows)+'\nResult: PASS\nProduction execution enabled: false.\n'
    (a.output/'summary.md').write_text(text);print(text)
if __name__=='__main__':main()
