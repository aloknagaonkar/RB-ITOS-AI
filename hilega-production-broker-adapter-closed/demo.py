"""Injected broker responses only; real HttpTransport remains closed."""
import argparse,json
from pathlib import Path
from adapter import Adapter,Store,FixtureTransport,HttpTransport,Blocked
from provider_mapping import draft
AT='2026-10-26T09:25:00+05:30'
def request(key):
    c=dict(instrument_key='NSE_FO|12345',underlying_key='NSE_INDEX|Nifty 50',instrument_type='CE',segment='NSE_FO',expiry='2026-10-27',lot_size=65,minimum_lot=65,freeze_quantity=1800)
    return draft(c,request_id=key,side='BUY',lots=1,as_of=AT)
def prepare(a,key):return a.prepare(request(key),signal_id='s-'+key,signal_at=AT,direction='BULLISH',reservation_reference='UNVERIFIED_EXPLICIT_FIXTURE_REFERENCE',as_of=AT)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    if a.output.exists():raise Blocked('USE_NEW_OUTPUT_DIRECTORY')
    a.output.mkdir(parents=True,mode=0o700);store=Store(a.output/'fixture.sqlite','EXPLICIT_OFFLINE_SCOPE','OFFLINE_FIXTURE');t=FixtureTransport(store);adapter=Adapter(store,t);rows=[]
    def note(stage,ok,state):
        rows.append(dict(stage=stage,status='PASS' if ok else 'FAIL',state=state))
        if not ok:raise AssertionError(stage)
    prepare(adapter,'entry1');ack=adapter.submit('entry1')
    note('Durable attempt and receipt bind acknowledgement, not fill',ack['state']=='ACKNOWLEDGED_NOT_FILLED' and adapter.status()['requests'][0]['filled'] is None,ack['state'])
    adapter=Adapter(store,FixtureTransport(store));adapter.recover();adapter.submit('entry1')
    note('Restart reads receipt without second request',len(t.orders())==1,adapter.status()['requests'][0]['state'])
    oid=adapter.status()['requests'][0]['order_id'];adapter.transport.fill(oid,20);adapter.cancel('entry1')
    note('Cancellation acknowledgement requires reconciliation',adapter.status()['requests'][0]['state']=='CANCEL_ACK_RECONCILE_REQUIRED',adapter.status()['requests'][0]['state'])
    adapter.reconcile_fixture();r=adapter.status()['requests'][0]
    note('Cancelled entry still has 20 filled; no flat claim',r['state']=='CANCELLED' and r['filled']==20 and r['remaining'] is None,r['state'])
    prepare(adapter,'entry2');adapter.transport.timeout_after=True;adapter.submit('entry2');adapter.submit('entry2');adapter.recover()
    r=next(x for x in adapter.status()['requests'] if x['request_id']=='entry2')
    note('Accepted timeout remains unknown with no blind retry',r['state']=='UNKNOWN' and r['order_id'] is None and len(t.orders())==2,r['state'])
    closed=Adapter(Store(a.output/'closed.sqlite','DRAFT_SCOPE_UNVERIFIED','LIVE_CLOSED'),HttpTransport(lambda:(_ for _ in ()).throw(AssertionError('TOKEN_MUST_NOT_BE_READ'))))
    prepare(closed,'closed');result=closed.submit('closed')
    note('Live gate blocks before token/network',result['status']=='PRODUCTION_MUTATIONS_CLOSED_IN_CODE' and not closed.status()['attempts'],result['status'])
    report=dict(status='PASS',stages=rows,fixture=adapter.status(),closed=closed.status(),evidence_mode='INJECTED_RESPONSES_AND_EXPLICIT_FIXTURE_STATUS_ONLY',orders_sent_to_upstox=False,production_execution_enabled=False)
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    text='# Broker adapter behind closed production gate\n\nInjected responses and fixture order status; no real HTTP request or fill/P&L proof.\n\n| Stage | Result | State |\n|---|---|---|\n'+''.join('| '+r['stage']+' | '+r['status']+' | '+r['state']+' |\n' for r in rows)+'\nResult: PASS\nProduction execution enabled: false.\n'
    (a.output/'summary.md').write_text(text);print(text)
if __name__=='__main__':main()
