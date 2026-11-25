"""Independent NIFTY simulation worker. No order APIs or legacy state imports."""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, time
import fcntl
import json
import os
from pathlib import Path
import signal
import threading
from .calendar import IST, session_day
from .data import OWN_ROOT, seed, load
from .live import Store


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--once',action='store_true');args=parser.parse_args()
    repo=args.repo.resolve();os.chdir(repo)
    root=repo/OWN_ROOT;root.mkdir(parents=True,exist_ok=True)
    lock=(root/'worker.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    # dotenv is already an application dependency. Credentials are only supplied
    # to the existing read-only candle source and are never printed or journaled.
    from dotenv import load_dotenv
    from market_lab.upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1
    load_dotenv(repo/'.env',override=False)
    source=UpstoxLiveShadowSourcesV1(os.environ.get('UPSTOX_ACCESS_TOKEN',''))
    store=Store(repo);stop=threading.Event();seeds={}
    signal.signal(signal.SIGTERM,lambda *_:stop.set());signal.signal(signal.SIGINT,lambda *_:stop.set())
    def process(day, now, rows):
        if day not in seeds:seeds[day]=seed(repo,day,source)
        warm,evidence=seeds[day]
        return store.ingest(day,rows,now,warm,evidence)
    try:
        # An interrupted prior-day simulation is finalized from exact historical
        # candles, never by carrying that owner into today's independent session.
        with closing(store.connect()) as db:
            pending=[(d,json.loads(s)) for d,s in db.execute('SELECT day,state FROM sessions')]
        from datetime import date
        for key,state in pending:
            day=date.fromisoformat(key)
            if day<datetime.now(IST).date() and (state['active'] or len(state['audits'])<(23 if key=='2026-11-08' else 125)):
                process(day,datetime.now(IST),load(repo,day,source))
        while not stop.is_set():
            now=datetime.now(IST);day=now.date()
            try:
                if session_day(day) and now.time()>=time(9,15):
                    current=store.view(day)
                    if len(current.get('audit',[]))==(23 if str(day)=='2026-11-08' else 125) and current.get('owner') is None:
                        store.health('SESSION_COMPLETE',session_date=str(day),last_completed_bar=current['audit'][-1]['decision_time'])
                        if args.once:break
                        stop.wait(15);continue
                    rows=[dict(timestamp=c.timestamp.isoformat(),open=c.open,high=c.high,low=c.low,close=c.close,
                                   volume=getattr(c,'volume',None)) for c in source.nifty_intraday_1m(now=now)]
                    result=process(day,now,rows)
                    print(json.dumps(dict(status=result['health']['status'],owner=result['owner'],
                        session_date=str(day),audits=len(result['audit']),execution_mode='SIMULATION_ONLY')),flush=True)
                else:store.health('OUTSIDE_REVIEWED_SESSION')
            except Exception as exc:
                store.health('BLOCKED',error_type=type(exc).__name__,reason=str(exc) if isinstance(exc,ValueError) else 'CANDLE_SOURCE_FAILED')
                print(json.dumps({'status':'BLOCKED','error_type':type(exc).__name__}),flush=True)
            if args.once:break
            stop.wait(15)
    finally:source.close();lock.close()

if __name__=='__main__':main()
