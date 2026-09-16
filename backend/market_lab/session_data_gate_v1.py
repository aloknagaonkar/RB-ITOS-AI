from __future__ import annotations
import argparse,csv,json
from dataclasses import asdict,dataclass,field
from datetime import datetime,date
from pathlib import Path
from typing import Any

DEFAULT_FUTURES_CSV=Path('data/historical-evidence/midpoint-v2-nifty-futures-vwap-v1-development.csv')
ALLOWED_BUCKETS=('train','oos-a','oos-b','oos-c','oos-d')

@dataclass
class Check:
    name:str
    status:str
    details:dict[str,Any]=field(default_factory=dict)

@dataclass
class SessionDataGateResult:
    session_date:str
    status:str
    checks:list[Check]
    repair_required:list[str]
    positioning_file:str|None=None
    option_ohlc_file:str|None=None
    futures_csv:str|None=None
    def to_dict(self):
        return {'session_date':self.session_date,'status':self.status,'repair_required':self.repair_required,'positioning_file':self.positioning_file,'option_ohlc_file':self.option_ohlc_file,'futures_csv':self.futures_csv,'checks':[asdict(x) for x in self.checks]}

def _load(path:Path): return json.loads(path.read_text())
def _rows(p):
    r=p.get('rows'); return r if isinstance(r,list) else []

def _select(data_root:Path,prefix:str,session_date:str):
    for bucket in ALLOWED_BUCKETS:
        d=data_root/f'{prefix}-{bucket}'
        if not d.exists(): continue
        exact=sorted(d.glob(f'*__{session_date}__{session_date}__*.json'))
        if exact: return exact[0]
    for bucket in ALLOWED_BUCKETS:
        d=data_root/f'{prefix}-{bucket}'
        if not d.exists(): continue
        for p in sorted(d.glob(f'*{session_date}*.json')):
            try:
                if str(_load(p).get('session_date'))==session_date: return p
            except Exception: pass
    return None

def _check_positioning(path,session_date):
    if path is None: return Check('POSITIONING','FAIL',{'reason':'MISSING'})
    try: p=_load(path)
    except Exception as e: return Check('POSITIONING','FAIL',{'reason':'UNREADABLE','error':str(e)})
    rows=_rows(p); reasons=[]
    if str(p.get('session_date'))!=session_date: reasons.append('SESSION_DATE_MISMATCH')
    if not rows: reasons.append('NO_ROWS')
    ce=sum(1 for r in rows if r.get('ce_instrument_key'))
    pe=sum(1 for r in rows if r.get('pe_instrument_key'))
    oi=sum(1 for r in rows if r.get('ce_oi') is not None and r.get('pe_oi') is not None)
    if not ce or not pe: reasons.append('CE_PE_INSTRUMENTS_MISSING')
    if not oi: reasons.append('OI_MISSING')
    times=[]
    for r in rows:
        try:
            ts=datetime.fromisoformat(str(r.get('timestamp')).replace('Z','+00:00'))
            if ts.date().isoformat()==session_date: times.append(ts)
        except Exception: pass
    times.sort()
    return Check('POSITIONING','PASS' if not reasons else 'FAIL',{'file':str(path),'row_count':len(rows),'ce_rows':ce,'pe_rows':pe,'rows_with_both_oi':oi,'first_timestamp':times[0].isoformat() if times else None,'last_timestamp':times[-1].isoformat() if times else None,'reasons':reasons})

def _check_option(path,session_date):
    if path is None: return Check('OPTION_OHLC','FAIL',{'reason':'MISSING'})
    try:p=_load(path)
    except Exception as e:return Check('OPTION_OHLC','FAIL',{'reason':'UNREADABLE','error':str(e)})
    rows=_rows(p); reasons=[]
    if str(p.get('session_date'))!=session_date: reasons.append('SESSION_DATE_MISMATCH')
    if not rows: reasons.append('NO_ROWS')
    sides={str(r.get('side')).upper() for r in rows if r.get('side')}
    inst={r.get('instrument_key') for r in rows if r.get('instrument_key')}
    strikes={r.get('strike') for r in rows if r.get('strike') is not None}
    bad=0; seen=set(); dup=0; times=[]
    for r in rows:
        try:
            o,h,l,c=map(float,(r['open'],r['high'],r['low'],r['close']))
            if h<max(o,c) or l>min(o,c) or h<l: bad+=1
        except Exception: bad+=1
        try:
            ts=datetime.fromisoformat(str(r['timestamp']).replace('Z','+00:00')); times.append(ts)
            k=(r.get('instrument_key'),ts.isoformat())
            if k in seen: dup+=1
            seen.add(k)
        except Exception: pass
    times.sort()
    if 'CE' not in sides or 'PE' not in sides: reasons.append('CE_OR_PE_SIDE_MISSING')
    if not inst: reasons.append('NO_INSTRUMENTS')
    if not strikes: reasons.append('NO_STRIKES')
    if bad: reasons.append('INVALID_OHLC')
    if dup: reasons.append('DUPLICATE_INSTRUMENT_TIMESTAMP')
    return Check('OPTION_OHLC','PASS' if not reasons else 'FAIL',{'file':str(path),'row_count':len(rows),'instrument_count':len(inst),'strike_count':len(strikes),'sides':sorted(sides),'first_timestamp':times[0].isoformat() if times else None,'last_timestamp':times[-1].isoformat() if times else None,'invalid_ohlc_rows':bad,'duplicate_instrument_timestamp_rows':dup,'reasons':reasons})

def _check_futures(path:Path,session_date):
    if not path.exists(): return Check('FUTURES','FAIL',{'reason':'CSV_MISSING','file':str(path)})
    with path.open(newline='') as h: rows=[r for r in csv.DictReader(h) if r.get('session_date')==session_date]
    reasons=[]; times=[]; seen=set(); dup=0; invalid=0
    for r in rows:
        try:
            ts=datetime.fromisoformat(r['timestamp'].replace('Z','+00:00')); times.append(ts)
            if r['timestamp'] in seen: dup+=1
            seen.add(r['timestamp'])
            o,hi,lo,c=map(float,(r['open'],r['high'],r['low'],r['close'])); v=float(r['volume']); vw=float(r['session_vwap'])
            if hi<max(o,c) or lo>min(o,c) or hi<lo or v<0 or vw<=0: invalid+=1
        except Exception: invalid+=1
    times.sort()
    if not rows: reasons.append('MISSING')
    if rows and len(rows)<300: reasons.append('TOO_FEW_1M_ROWS')
    if times and times[0].strftime('%H:%M')>'09:15': reasons.append('STARTS_AFTER_09_15')
    if times and times[-1].strftime('%H:%M')<'15:29': reasons.append('ENDS_BEFORE_15_29')
    if dup: reasons.append('DUPLICATE_TIMESTAMPS')
    if invalid: reasons.append('INVALID_OHLCV_OR_VWAP')
    inst=sorted({r.get('instrument_key') for r in rows if r.get('instrument_key')})
    exp=sorted({r.get('expiry') for r in rows if r.get('expiry')})
    src=sorted({r.get('contract_source') for r in rows if r.get('contract_source')})
    if len(inst)>1: reasons.append('MULTIPLE_FUTURES_CONTRACTS')
    if len(exp)>1: reasons.append('MULTIPLE_FUTURES_EXPIRIES')
    return Check('FUTURES','PASS' if not reasons else 'FAIL',{'file':str(path),'row_count':len(rows),'instrument_keys':inst,'expiries':exp,'contract_sources':src,'first_timestamp':times[0].isoformat() if times else None,'last_timestamp':times[-1].isoformat() if times else None,'duplicate_timestamps':dup,'invalid_rows':invalid,'reasons':reasons})

def _check_baseline(pos:Check,session_date):
    if pos.status!='PASS': return Check('SESSION_BASELINE_09_20','FAIL',{'reason':'POSITIONING_NOT_VALID'})
    p=_load(Path(pos.details['file'])); matches=[]
    for r in _rows(p):
        try:
            ts=datetime.fromisoformat(str(r.get('timestamp')).replace('Z','+00:00'))
            if ts.date().isoformat()==session_date and ts.strftime('%H:%M')=='09:20': matches.append(r)
        except Exception: pass
    usable=[r for r in matches if r.get('ce_oi') is not None and r.get('pe_oi') is not None]
    return Check('SESSION_BASELINE_09_20','PASS' if usable else 'FAIL',{'matching_rows':len(matches),'usable_oi_rows':len(usable),'reason':None if usable else 'GENUINE_09_20_BASELINE_UNAVAILABLE'})

def validate_session(session_date:str,*,data_root='data',futures_csv=DEFAULT_FUTURES_CSV):
    date.fromisoformat(session_date); root=Path(data_root)
    pf=_select(root,'historical-positioning-cache',session_date); of=_select(root,'historical-option-ohlc-cache',session_date)
    pos=_check_positioning(pf,session_date); opt=_check_option(of,session_date); fut=_check_futures(Path(futures_csv),session_date); base=_check_baseline(pos,session_date)
    checks=[pos,opt,fut,base]; repair=[]
    if pos.status!='PASS': repair.append('POSITIONING')
    if opt.status!='PASS': repair.append('OPTION_OHLC')
    if fut.status!='PASS': repair.append('FUTURES')
    if base.status!='PASS' and 'POSITIONING' not in repair: repair.append('SESSION_BASELINE_09_20')
    return SessionDataGateResult(session_date,'PASS' if not repair else 'FAIL',checks,repair,str(pf) if pf else None,str(of) if of else None,str(futures_csv))

def main():
    p=argparse.ArgumentParser(); p.add_argument('--session-date',required=True); p.add_argument('--data-root',default='data'); p.add_argument('--futures-csv',default=str(DEFAULT_FUTURES_CSV)); a=p.parse_args()
    r=validate_session(a.session_date,data_root=a.data_root,futures_csv=a.futures_csv); print(json.dumps(r.to_dict(),indent=2)); raise SystemExit(0 if r.status=='PASS' else 2)
if __name__=='__main__': main()
