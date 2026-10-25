"""Offline Upstox-shaped fixture demonstration. No credentials or HTTP calls."""
import argparse,json
from pathlib import Path
from mapping import draft,place_ack,cancel_ack,DisabledMutations,Blocked,match
AT='2026-10-26T09:25:00+05:30'
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise Blocked('USE_NEW_OUTPUT_DIRECTORY')
    a.output.mkdir(parents=True,mode=0o700)
    contract=dict(instrument_key='NSE_FO|12345',underlying_key='NSE_INDEX|Nifty 50',instrument_type='CE',segment='NSE_FO',expiry='2026-10-27',lot_size=65,minimum_lot=65,freeze_quantity=1800)
    request=draft(contract,request_id='offline-fixture',side='BUY',lots=1,as_of=AT);stages=[]
    try:DisabledMutations().submit(request)
    except Blocked as exc:stages.append(dict(stage='Attempt production submission',status=str(exc)))
    stages.append(dict(stage='V3 placement acknowledgement',**place_ack(dict(status='success',data=dict(order_ids=['fixture-1'])))))
    stages.append(dict(stage='Ambiguous split acknowledgement',**place_ack(dict(status='success',data=dict(order_ids=['fixture-1','fixture-2'])))))
    snapshot=dict(status='READ_ONLY_CAPTURED',account_scope='OFFLINE_FIXTURE',account_identity_verified=True,
        generated_at=AT,completed_at=AT,production_execution_enabled=False,entry_permission=False,
        orders=[dict(order_id='fixture-1',instrument='NSE_FO|12345',product='I',side='BUY',quantity=65,filled=20,pending=0,status='CANCELLED')],
        trades=[dict(order_id='fixture-1',trade_id='trade-1',instrument='NSE_FO|12345',product='I',side='BUY',quantity=20,price='100')])
    stages.append(dict(stage='Cancelled order with partial fills',**match(request,snapshot,'fixture-1',expected_account_scope='OFFLINE_FIXTURE',as_of=AT)))
    stages.append(dict(stage='Cancellation acknowledgement',**cancel_ack(dict(status='success',data=dict(order_id='fixture-1')),'fixture-1')))
    ok=stages[0]['status']=='UPSTOX_PRODUCTION_SUBMISSION_DISABLED_IN_CODE' and stages[1]['fill_confirmed'] is False and stages[2]['retry_allowed'] is False and stages[3]['flat_confirmed'] is False and stages[4]['flat_confirmed'] is False
    report=dict(status='PASS' if ok else 'FAIL',stages=stages,draft=request,production_execution_enabled=False,orders_sent=False,evidence_mode='OFFLINE_UPSTOX_SHAPED_FIXTURES')
    (a.output/'report.json').write_text(json.dumps(report,indent=2));(a.output/'draft.json').write_text(json.dumps(request,indent=2))
    text='# Disabled Upstox-specific adapter mapping\n\nOffline fixtures only. No broker calls or ownership claims.\n\n| Stage | Result |\n|---|---|\n'+''.join('| '+x['stage']+' | '+x['status']+' |\n' for x in stages)+'\nResult: '+report['status']+'\nProduction submission disabled in code.\n'
    (a.output/'summary.md').write_text(text);print(text);return 0 if ok else 2
if __name__=='__main__':raise SystemExit(main())
