"""Synthetic arithmetic only. No API credentials or actual orders."""
import argparse,json
from pathlib import Path
from ledger import Ledger,Blocked
DAY='2026-10-26';AT=DAY+'T09:25:00+05:30'
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    if a.output.exists():raise Blocked('USE_FRESH_OUTPUT_DIRECTORY')
    a.output.mkdir(parents=True,mode=0o700);l=Ledger(a.output/'allocation.sqlite','SYNTHETIC_ACCOUNT');stages=[]
    l.snapshot('cash1',cash='100000',observed_at=AT,as_of=AT,session_date=DAY)
    legs=[dict(instrument='FIXTURE|CE'+str(o),side='CE',offset=o,lot_size=65,lots=1,quantity=65,ask='100',buffer='100') for o in [-2,-1,0,1,2]]
    def note(name,result):stages.append(dict(stage=name,result=result,held=l.status()['held_total']))
    l.reserve('basket1',signal_id='signal1',snapshot_id='cash1',legs=legs,as_of=AT,session_date=DAY);note('First five-strike basket','RESERVED')
    try:l.reserve('basket2',signal_id='signal2',snapshot_id='cash1',legs=legs,as_of=AT,session_date=DAY)
    except Blocked as exc:note('Competing basket',str(exc))
    l.evidence('unknown','basket1',state='UNKNOWN',as_of=AT);note('Response outcome unknown','HOLD_RETAINED')
    l.evidence('partial','basket1',state='PARTIAL',as_of=AT);note('Partial fill confirmed','HOLD_RETAINED')
    l.evidence('filled','basket1',state='FILLED',as_of=AT);note('Full entry fill confirmed','HOLD_RETAINED_FOR_EXPOSURE')
    l.evidence('flat','basket1',state='RELEASED',as_of=AT,terminal_no_exposure=True);note('Explicit terminal and flat fixture','RELEASED')
    ok=[x['held'] for x in stages]==['33000.00']*5+['0.00']
    report=dict(status='PASS' if ok else 'FAIL',stages=stages,ledger=l.status(),production_execution_enabled=False,orders_sent=False)
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    text='# Offline allocation reservation demonstration\n\nSynthetic INR100,000 cash; INR50,000 cap. Not NIFTY points or broker execution.\n\n| Stage | Result | Held INR |\n|---|---|---:|\n'
    text+=''.join('| '+x['stage']+' | '+x['result']+' | '+x['held']+' |\n' for x in stages)
    text+='\nResult: '+report['status']+'\nNot wired to execution. No orders sent.\n'
    (a.output/'summary.md').write_text(text);print(text);return 0 if ok else 2
if __name__=='__main__':raise SystemExit(main())
