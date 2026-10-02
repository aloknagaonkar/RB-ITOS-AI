#!/usr/bin/env python3
"""Read-only B/E exit-policy comparison on the 12 post-08-Sep forward sessions.

Requires the frozen two full 1m CSVs. This study compares underlying close
points only. Dates and rules are fixed; no option P&L or live mutation.
"""
from __future__ import annotations
import importlib.util
import statistics
from collections import Counter
from datetime import datetime,timedelta
from pathlib import Path

MATERIALIZER=Path('scripts/midpoint_m2_materialize_forward_oos_replay.py')
V57=Path('scripts/midpoint_v57_full_historical_be_lifecycle_replay.py')
POLICIES=Path('midpoint_be_exit_policy_research.py')
START,END='2026-09-09','2026-09-28'

def load(path,name):
    if not path.is_file():raise SystemExit(f'STOP missing source: {path}')
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

def expected_minutes(day):
    t=datetime.fromisoformat(day+'T09:15:00+05:30')
    return {(t+timedelta(minutes=i)).isoformat() for i in range(360)}

def summary(label,rows):
    print('\n'+label,'completed',len(rows))
    for policy in ('CAP20_ONLY','DEGRADED_EXIT','FIRST_ELIGIBLE_REBREAK_EXIT'):
        vals=[r['points'][policy] for r in rows]
        delta=[r['points'][policy]-r['points']['CAP20_ONLY'] for r in rows]
        changed=[r for r in rows if r['exit'][policy]!=r['exit']['CAP20_ONLY']]
        print(policy,{'n':len(vals),'changed':len(changed),'sum':round(sum(vals),2),
            'mean':round(statistics.mean(vals),2) if vals else None,
            'median':round(statistics.median(vals),2) if vals else None,
            'positive':sum(x>0 for x in vals),'delta_sum':round(sum(delta),2),
            'improved':sum(x>0 for x in delta),'harmed':sum(x<0 for x in delta),
            'changed_delta_mean':round(statistics.mean([r['points'][policy]-r['points']['CAP20_ONLY'] for r in changed]),2) if changed else None})

def main():
    source=load(MATERIALIZER,'forward_sep_source')
    v57=load(V57,'forward_sep_v57')
    policy=load(POLICIES,'forward_sep_policy')
    for path in (source.U,source.F):
        if not path.is_file():raise SystemExit(f'STOP missing exact 1m CSV: {path}')
    u=source.load_underlying();f=source.load_futures()
    days=sorted(set(u)&set(f))
    if len(days)!=12 or any(not START<=d<=END for d in days):
        raise SystemExit(f'STOP expected 12 post-08-Sep sessions through Sep28; got {days}')
    trades=[];unresolved=Counter();entries=Counter()
    for day in days:
        required=expected_minutes(day)
        if set(u[day])!=required or set(f[day])!=required:
            raise SystemExit(f'STOP {day}: full 09:15-15:14 exact 1m coverage failed underlying={len(u[day])} futures={len(f[day])}')
        audit,_,_=v57.replay_session(day,u[day],f[day])
        en=[(i,r) for i,r in enumerate(audit) if r.get('event_type') in ('B_ENTRY','E_ENTRY')]
        for j,(i,e) in enumerate(en):
            if e['family'] not in ('B','E'):raise SystemExit('STOP non-B/E entry')
            entries[e['family']]+=1
            end=en[j+1][0] if j+1<len(en) else len(audit)
            record=policy.one_trade(e,audit[i:end])
            if record is None:unresolved[e['family']]+=1
            else:record.update(session_date=day);trades.append(record)
        print(day,'entries',len(en),'completed',sum(t['session_date']==day for t in trades),flush=True)
    print('\nSOURCE 12 full forward sessions; entries',dict(entries),'unresolved',dict(unresolved))
    for fam in ('B','E','B+E'):
        summary(fam,[r for r in trades if fam=='B+E' or r['family']==fam])
    print('\nUnderlying close-based shadow points; no historical option tape, spreads, charges, quantity or orders.')

if __name__=='__main__':main()
