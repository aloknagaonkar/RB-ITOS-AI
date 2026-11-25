"""Validated input discovery. Existing evidence is read-only; recovery has its own root."""
from datetime import date, datetime, time, timedelta
from pathlib import Path
import hashlib
import json
import os
from . import STRATEGY_ID, VERSION
from .calendar import (IST, SPECIAL, UNDERLYING, validate_rows, read_session,
                       required_sessions, session_day, fetch_session, save_session)

ROOTS = ('data/historical-evidence/hilega-rsi-two-route-v1/inputs',
         'data/historical-evidence/hilega-3m-warmup-verified-v1',
         'data/historical-evidence/hilega-milega-underlying-cache-v1',
         'data/recovery/october-2026/replay-input/replay-warmup',
         'data/recovery/october-2026/nifty-cache')
OWN_ROOT = 'data/historical-evidence/hilega-rsi-two-route-v1'

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def atomic_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    from tempfile import NamedTemporaryFile
    with NamedTemporaryFile('w',dir=path.parent,delete=False) as f:
        temp=Path(f.name)
        json.dump(value,f,allow_nan=False);f.flush();os.fsync(f.fileno())
    try:os.replace(temp,path)
    finally:temp.unlink(missing_ok=True)

def aggregate(rows):
    if len(rows)%3:raise ValueError('INCOMPLETE_3M_INPUT')
    return [dict(start=rows[i]['timestamp'],open=rows[i]['open'],
        high=max(r['high'] for r in rows[i:i+3]),low=min(r['low'] for r in rows[i:i+3]),
        close=rows[i+2]['close']) for i in range(0,len(rows),3)]

def aggregate_objects(objects, day):
    return aggregate([dict(timestamp=r.timestamp.isoformat(),open=r.open,high=r.high,low=r.low,close=r.close) for r in objects])

def bars(rows, day):
    rows=validate_rows(rows,day)
    return aggregate(rows[1:] if day==SPECIAL else rows)

def candidates(repo, day):
    return [Path(repo)/r/(str(day)+'.json') for r in ROOTS]

def load(repo, day, source=None):
    failures=[]
    for path in candidates(repo,day):
        if path.exists():
            try:return read_session(path,day)
            except (ValueError,KeyError,TypeError,OSError) as exc:failures.append(type(exc).__name__)
    if source is None:raise ValueError('MISSING_OR_INVALID_CANDLES:'+str(day))
    rows=fetch_session(source,day)
    save_session(Path(repo)/ROOTS[0],day,rows)
    return rows

def seed(repo, day, source=None):
    sessions=[(str(d),load(repo,d,source)) for d in required_sessions(day)]
    evidence=dict(sessions=[d for d,_ in sessions],sha256={d:digest(r) for d,r in sessions},
                  calendar='BOUNDED_RECENT_20_EXPECTED_SESSIONS_2026_V2')
    return [b for d,rows in sessions for b in bars(rows,date.fromisoformat(d))],evidence

def code_hash():
    return digest({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob('*.py'))})

def replay(repo, day, source=None):
    from .engine import Engine
    if not session_day(day):raise ValueError('NON_TRADING_SESSION')
    rows=load(repo,day,source);warm,evidence=seed(repo,day,source)
    identity=dict(strategy_id=STRATEGY_ID,version=VERSION,code_sha256=code_hash(),
                  target_sha256=digest(rows),warmup=evidence)
    key=digest(identity);out=Path(repo)/OWN_ROOT/'replay'/str(day)/(key+'.json')
    if out.exists():
        try:
            result=json.loads(out.read_text())
            checksum=result.pop('result_sha256',None)
            if (result.get('input_evidence')==identity and result.get('status')=='COMPLETE'
                    and result.get('strategy_id')==STRATEGY_ID and result.get('strategy_version')==VERSION
                    and result.get('cache_key')==key and checksum==digest(result)):
                result['result_sha256']=checksum
                return result
        except (ValueError,TypeError,AttributeError):
            pass  # Recompute only this strategy's corrupt derived cache.

    engine=Engine(str(day),warm)
    for bar in bars(rows,day):engine.advance(bar,rows)
    if engine.active:raise ValueError('SESSION_EXIT_MISSING')
    result=dict(engine.result(),status='COMPLETE',input_evidence=identity,cache_key=key)
    result['result_sha256']=digest(result)
    atomic_json(out,result);atomic_json(out.parent/'latest.json',{'cache_key':key,'strategy_version':VERSION})
    return result

def registry(repo, start, end):
    if (end-start).days>366 or end<start:raise ValueError('INVALID_DATE_RANGE')
    out=[];day=start
    while day<=end:
        if session_day(day):
            try:load(repo,day);status='CANDLES_AVAILABLE'
            except ValueError:status='CANDLES_MISSING'
            missing=[]
            for d in required_sessions(day):
                try:load(repo,d)
                except ValueError:missing.append(str(d))
            out.append(dict(session_date=str(day),status=status,missing_warmup=missing))
        day+=timedelta(days=1)
    return out
