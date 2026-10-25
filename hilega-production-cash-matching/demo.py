"""Offline evidence-contract demonstration. All amounts and proofs synthetic."""
import argparse,json
from pathlib import Path
from matcher import evaluate
AT='2026-10-26T09:25:00+05:30'
def fixture(state='FILLED',proof=True,reflected='6500',flat=False,external=False):
    snapshot=dict(evidence_mode='OFFLINE_FIXTURE',account_scope='FIXTURE',snapshot_id='s1',observed_at=AT,complete=True,coherent=True,
        available_cash='93500',unrelated_cash_activity=external,
        orders=[dict(order_id='o1',instrument='FIXTURE|CE',product='I',side='BUY',quantity=65,filled=65,pending=0,status='FILLED')],
        positions=[dict(instrument='FIXTURE|CE',product='I',quantity=0 if flat else 65)])
    rows=[dict(reservation_id='r1',account_scope='FIXTURE',reserved_amount='6600',order_id='o1',instrument='FIXTURE|CE',product='I',quantity=65,state=state)]
    proofs=[dict(reservation_id='r1',account_scope='FIXTURE',snapshot_id='s1',order_id='o1',kind='EXPLICIT_OFFLINE_ATTRIBUTION_ASSERTION',reflected_amount=reflected,
        all_related_orders_terminal=flat,all_exit_fills_verified=flat)] if proof else []
    return evaluate(snapshot,rows,proofs,as_of=AT)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise ValueError('USE_NEW_OUTPUT_DIRECTORY')
    a.output.mkdir(parents=True,mode=0o700)
    scenarios=[('Filled: explicit reflection',fixture()),('Missing attribution',fixture(proof=False)),
        ('Partial reflected amount',fixture(state='PARTIAL',reflected='2000')),('Acceptance unknown',fixture(state='UNKNOWN')),
        ('Exit pending',fixture(state='EXIT_PENDING')),('Verified terminal flat',fixture(state='TERMINAL_FLAT',flat=True)),
        ('Unrelated cash activity',fixture(external=True))]
    ok=(scenarios[0][1]['unreflected_hold_deduction']=='100.00' and scenarios[1][1]['new_entry_eligibility_blocked']
        and scenarios[3][1]['full_local_holds']=='6600.00' and scenarios[5][1]['full_local_holds']=='0.00'
        and scenarios[6][1]['new_entry_eligibility_blocked'])
    report=dict(status='PASS' if ok else 'FAIL',scenarios=[dict(scenario=n,**r) for n,r in scenarios],production_execution_enabled=False,orders_sent=False)
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    text='# Offline cash/local-hold matching\n\nExplicit synthetic attribution assertions, not Upstox evidence. No real ledger updates.\n\n| Scenario | Full local hold INR | Reflected overlap INR | Unreflected deduction INR | Status |\n|---|---:|---:|---:|---|\n'
    text+=''.join('| '+name+' | '+r['full_local_holds']+' | '+r['explicitly_reflected_overlap']+' | '+r['unreflected_hold_deduction']+' | '+r['status']+' |\n' for name,r in scenarios)
    text+='\nResult: '+report['status']+'\nReal debit attribution: NOT_VALIDATED. Production execution: false.\n'
    (a.output/'summary.md').write_text(text);print(text);return 0 if ok else 2
if __name__=='__main__':raise SystemExit(main())
