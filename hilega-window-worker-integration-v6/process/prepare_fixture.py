"""Generate signed SYNTHETIC evidence only in an explicitly marked disposable workspace."""
import argparse,json,sys
from pathlib import Path
from datetime import datetime
from fixture_clock import now
from window import need,save

def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--workspace',type=Path,required=True);p.add_argument('--evidence',action='store_true');a=p.parse_args();current=now(a.workspace)
    sys.path[:0]=[str(a.bundle/'backend'),str(a.bundle/'runtime')]
    from hilega_application_preparation_fixtures import bundle,PIN,T,resign_cash
    if not a.evidence:
        from market_lab.hilega_execution_port_v1.adapter import Store
        Store(a.workspace/'adapter.sqlite',PIN['scope'],'LIVE_CLOSED')
        save(a.workspace/'synthetic-pin.json',dict(PIN,model='HILEGA_UPSTOX_ACCOUNT_PIN_V1',broker='UPSTOX',approved_at=T.isoformat()))
        return 0
    value=bundle();delta=current-T
    # Complete evidence at the current fixture clock, without future timestamps.
    from datetime import timedelta
    delta-=timedelta(seconds=3)
    def shift(x):
        if isinstance(x,dict):return {k:shift(v) for k,v in x.items()}
        if isinstance(x,list):return [shift(v) for v in x]
        if isinstance(x,str) and 'T' in x:
            try:
                dt=datetime.fromisoformat(x)
                if dt.tzinfo:return (dt+delta).isoformat()
            except ValueError:pass
        return x
    value=shift(value);resign_cash(value);save(a.workspace/'synthetic-evidence.json',value);return 0
if __name__=='__main__':raise SystemExit(main())
