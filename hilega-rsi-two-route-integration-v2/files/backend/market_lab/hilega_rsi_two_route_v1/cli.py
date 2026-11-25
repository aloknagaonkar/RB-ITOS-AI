import argparse
from datetime import date, timedelta
import json
import os
from pathlib import Path
from .calendar import session_day
from .data import replay

def main():
    p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True)
    p.add_argument('--from',dest='start',type=date.fromisoformat,required=True)
    p.add_argument('--through',type=date.fromisoformat,required=True)
    p.add_argument('--recover-missing',action='store_true');a=p.parse_args()
    if a.through<a.start or (a.through-a.start).days>366:p.error('Invalid date range')
    source=None
    if a.recover_missing:
        from dotenv import load_dotenv
        from market_lab.upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1
        load_dotenv(a.repo/'.env');source=UpstoxLiveShadowSourcesV1(os.environ.get('UPSTOX_ACCESS_TOKEN',''))
    day=a.start;failed=0
    try:
        while day<=a.through:
            if session_day(day):
                try:
                    r=replay(a.repo,day,source)
                    print(json.dumps(dict(session_date=str(day),status='PASS',**r['summary'])),flush=True)
                except Exception as exc:
                    failed+=1;print(json.dumps(dict(session_date=str(day),status='BLOCKED',error_type=type(exc).__name__,reason=str(exc) if isinstance(exc,ValueError) else 'REPLAY_FAILED')),flush=True)
            day+=timedelta(days=1)
    finally:
        if source:source.close()
    raise SystemExit(1 if failed else 0)
if __name__=='__main__':main()
