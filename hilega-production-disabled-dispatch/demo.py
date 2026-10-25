"""Offline durable broker-request draft demonstration. No network or app changes."""
import argparse,json
from pathlib import Path
from dispatch import Outbox,Blocked
from provider_mapping import draft
AT='2026-10-26T09:25:00+05:30'
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise Blocked('USE_NEW_OUTPUT_DIRECTORY')
    a.output.mkdir(parents=True,mode=0o700);box=Outbox(a.output/'disabled.sqlite','EXPLICIT_OFFLINE_DRAFT_SCOPE')
    contract=dict(instrument_key='NSE_FO|12345',underlying_key='NSE_INDEX|Nifty 50',instrument_type='CE',segment='NSE_FO',expiry='2026-10-27',lot_size=65,minimum_lot=65,freeze_quantity=1800)
    r=draft(contract,request_id='entry',side='BUY',lots=1,as_of=AT)
    prepared=box.prepare(r,signal_id='s1',signal_at=AT,direction='BULLISH',as_of=AT)
    refused=box.attempt_submission('entry');restarted=Outbox(box.path,box.scope);again=restarted.attempt_submission('entry')
    ackblocked=False
    try:restarted.import_acknowledgement('entry',dict(status='success',data=dict(order_ids=['synthetic-id'])))
    except Blocked:ackblocked=True
    ok=prepared['state']=='PREPARED_DISABLED' and refused['orders_sent'] is False and again['orders_sent'] is False and ackblocked
    report=dict(status='PASS' if ok else 'FAIL',prepared=prepared,refused=refused,after_restart=again,manual_ack_import_blocked=ackblocked,outbox=restarted.status(),orders_sent=False)
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    text='# Disabled broker dispatch boundary\n\nSynthetic contract metadata; no HTTP transport or app changes.\n\n| Stage | Result |\n|---|---|\n| Request draft durable | '+prepared['state']+' |\n| Submission attempt | '+refused['status']+' |\n| Restart/repeat | '+again['status']+' |\n| Manual acknowledgement import | '+('BLOCKED' if ackblocked else 'FAIL')+' |\n\nResult: '+report['status']+'\nProduction execution enabled: false.\n'
    (a.output/'summary.md').write_text(text);print(text);return 0 if ok else 2
if __name__=='__main__':raise SystemExit(main())
