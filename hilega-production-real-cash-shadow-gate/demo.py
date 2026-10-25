"""Offline synthetic cash capacity/hold demonstration; no broker calls."""
import argparse,json
from gate import ShadowBook,Blocked
from synthetic_evidence import AT,PIN,capture
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    if a.output.exists():raise Blocked('USE_FRESH_OUTPUT_DIRECTORY')
    a.output.mkdir(parents=True,mode=0o700);book=ShadowBook(a.output/'synthetic.sqlite',PIN['scope']);rows=[]
    def note(name,result):rows.append(dict(stage=name,status=result['status'],held=result['full_local_holds'],capacity=result['conservative_capacity'],entry_permission=result['entry_permission']))
    note('Synthetic net cash 100000, half-cash cap 50000',book.preview(capture(),PIN,as_of=AT))
    book.reserve_shadow('plan1','6600',capture(),PIN,as_of=AT)
    note('Unsubmitted shadow proposal retains full hold',book.preview(capture(),PIN,as_of=AT))
    book=ShadowBook(book.path,PIN['scope'])
    note('Restart preserves shadow hold',book.preview(capture(),PIN,as_of=AT))
    book.mark_unknown('plan1')
    note('Unknown outcome: no reflection credit or release',book.preview(capture(),PIN,as_of=AT))
    blocked=False
    try:book.cancel_unsubmitted_shadow('plan1')
    except Blocked:blocked=True
    other=ShadowBook(a.output/'explicit-unsubmitted.sqlite',PIN['scope'])
    other.reserve_shadow('plan2','6600',capture(),PIN,as_of=AT);other.cancel_unsubmitted_shadow('plan2')
    note('Separate never-submitted shadow proposal explicitly cancelled',other.preview(capture(),PIN,as_of=AT))
    ok=blocked and rows[1]['held']=='6600.00' and rows[3]['status']=='REVIEW_REQUIRED' and rows[-1]['held']=='0.00' and all(r['entry_permission'] is False for r in rows)
    report=dict(status='PASS' if ok else 'FAIL',stages=rows,evidence_mode='EXPLICIT_SYNTHETIC_FIXTURE_ONLY',debit_attribution='NOT_VALIDATED',production_execution_enabled=False,orders_sent=False)
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    text='# Cash gate: offline shadow holds\n\nSynthetic INR only; no actual cash/fill evidence.\n\n| Stage | Status | Held INR | Capacity INR |\n|---|---|---:|---:|\n'+''.join('| '+r['stage']+' | '+r['status']+' | '+r['held']+' | '+r['capacity']+' |\n' for r in rows)+'\nResult: '+report['status']+'\nProduction execution enabled: false.\n'
    (a.output/'summary.md').write_text(text);print(text);return 0 if ok else 2
if __name__=='__main__':raise SystemExit(main())
