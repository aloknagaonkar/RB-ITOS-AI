"""Exact historical session repair; no synthetic candles or validation relaxation."""
from datetime import datetime,time,timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import uuid
from zoneinfo import ZoneInfo

IST=ZoneInfo('Asia/Kolkata');UNDERLYING='NSE_INDEX|Nifty 50'


def need(ok,reason):
    if not ok:raise ValueError(reason)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def rows_by_minute(rows,day):
    out={}
    for row in rows:
        t=datetime.fromisoformat(row['timestamp'].replace('Z','+00:00'))
        need(t.tzinfo is not None,'AWARE_CANDLE_TIMESTAMP_REQUIRED');t=t.astimezone(IST)
        if t.date()!=day or not time(9,15)<=t.time()<=time(15,29):continue
        need(t.second==t.microsecond==0,'EXACT_ONE_MINUTE_TIMESTAMP_REQUIRED')
        need(t not in out,'DUPLICATE_SESSION_MINUTE')
        values=[row[k] for k in ('open','high','low','close')]
        need(all(type(x) in (int,float) and math.isfinite(x) and x>0 for x in values),'INVALID_OHLC_VALUE')
        o,h,l,c=values;need(l<=min(o,c)<=max(o,c)<=h,'INCONSISTENT_OHLC_RANGE')
        safe=dict(timestamp=t.isoformat(),open=float(o),high=float(h),low=float(l),close=float(c))
        for key in ('volume','open_interest'):
            value=row.get(key);need(value is None or type(value) in (int,float) and math.isfinite(value) and value>=0 and int(value)==value,'INVALID_VOLUME_OR_OI')
            safe[key]=None if value is None else int(value)
        out[t]=safe
    return out


def missing_minutes(rows,day):
    grid=rows_by_minute(rows,day);start=datetime.combine(day,time(9,15),tzinfo=IST)
    return [(start+timedelta(minutes=i)).strftime('%H:%M') for i in range(375) if start+timedelta(minutes=i) not in grid]


def normalize_v3(body,day):
    need(isinstance(body,dict) and body.get('status')=='success' and isinstance(body.get('data'),dict),'HISTORICAL_RESPONSE_INVALID')
    raw=body['data'].get('candles');need(isinstance(raw,list),'HISTORICAL_CANDLES_MISSING');rows=[]
    for r in raw:
        need(isinstance(r,list) and len(r)>=5,'INCOMPLETE_HISTORICAL_ROW')
        rows.append(dict(timestamp=r[0],open=r[1],high=r[2],low=r[3],close=r[4],
            volume=r[5] if len(r)>5 else None,open_interest=r[6] if len(r)>6 else None))
    selected=rows_by_minute(rows,day);return [selected[k] for k in sorted(selected)]


def proposed_cache(old,candidate,day,*,accept_revisions=False):
    need(set(old)=={'schema_version','underlying','session_date','candles'} and old['schema_version']==1
        and old['underlying']==UNDERLYING and old['session_date']==day.isoformat(),'EXACT_OPERATIONAL_CACHE_HEADER_REQUIRED')
    missing=missing_minutes(candidate,day);need(not missing,'PROVIDER_SESSION_INCOMPLETE: '+','.join(missing))
    prior=rows_by_minute(old['candles'],day);fresh=rows_by_minute(candidate,day)
    changed=[t.strftime('%H:%M') for t,row in prior.items() if fresh[t]!=row]
    need(accept_revisions or not changed,'OVERLAPPING_BROKER_VALUES_CHANGED: '+','.join(changed[:20]))
    return dict(old,candles=[fresh[k] for k in sorted(fresh)]),changed


def atomic_repair(path,old_raw,payload,backup,*,checkpoint=lambda:None):
    need(path.is_file() and not any(p.is_symlink() for p in [path,*path.absolute().parents]),'REGULAR_OPERATIONAL_CACHE_REQUIRED')
    need(path.read_bytes()==old_raw,'CACHE_CHANGED_BEFORE_REPAIR')
    data=(json.dumps(payload,indent=2,allow_nan=False)+'\n').encode();mode=stat.S_IMODE(path.stat().st_mode)
    fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(old_raw);stream.flush();os.fsync(stream.fileno())
    temp=path.with_name(path.name+'.warmup-new-'+uuid.uuid4().hex)
    try:
        fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        checkpoint();need(path.read_bytes()==old_raw,'CACHE_CHANGED_DURING_REPAIR')
        os.replace(temp,path)
        fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if temp.exists():temp.unlink()
    need(path.read_bytes()==data and backup.read_bytes()==old_raw,'REPAIR_OR_BACKUP_VERIFICATION_FAILED')
    return dict(original_sha256=sha(old_raw),repaired_sha256=sha(data),backup=str(backup))


def preserve_existing_overlap(old,candidate,day):
    """Tail repair only: retain prior OI, require exact OHLC and volume equality."""
    prior=rows_by_minute(old['candles'],day);fresh=rows_by_minute(candidate,day)
    need(not missing_minutes(candidate,day),'PROVIDER_SESSION_INCOMPLETE')
    differences=[]
    for stamp,previous in prior.items():
        current=fresh[stamp]
        need(all(previous[k]==current[k] for k in ('open','high','low','close','volume')),
             'OVERLAPPING_PRICE_OR_VOLUME_CHANGED: '+stamp.strftime('%H:%M'))
        if previous['open_interest']!=current['open_interest']:
            differences.append(dict(minute=stamp.strftime('%H:%M'),cached_open_interest=previous['open_interest'],broker_open_interest=current['open_interest']))
        fresh[stamp]=previous
    merged=[fresh[k] for k in sorted(fresh)]
    need(not missing_minutes(merged,day),'MERGED_SESSION_INCOMPLETE')
    return merged,differences
