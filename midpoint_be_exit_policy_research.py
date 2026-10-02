#!/usr/bin/env python3
"""Read-only matched B/E exit comparison over the frozen V55/V57 480 sessions.

All values are NIFTY directional shadow points at completed 1m closes. No
option premiums, fees, orders, quantity, live audit changes, or threshold tuning.
"""
from __future__ import annotations
import importlib.util
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

V55 = Path('scripts/midpoint_v55_boundary_selection_replay.py')
V52 = Path('scripts/midpoint_mature_boundary_robustness_v52_1.py')
CANON = Path('scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py')
V57 = Path('scripts/midpoint_v57_full_historical_be_lifecycle_replay.py')
EXPECTED = {
 'B1_2024-08-16_to_2025-02-05': {'E':51,'B':30,'OTHER_FRESH_A':101},
 'B2_2025-02-06_to_2025-07-16': {'E':61,'B':41,'OTHER_FRESH_A':70},
 'B3_2025-07-17_to_2025-12-11': {'E':56,'B':39,'OTHER_FRESH_A':82},
 'B4_2025-12-12_to_2026-09-08': {'E':103,'B':78,'OTHER_FRESH_A':148},
}

def load(path, name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def points(entry, event):
    price=event.get('underlying_price')
    if price is None: return None
    price=float(price)
    return price-float(entry['underlying_price']) if entry['direction']=='BULLISH' else float(entry['underlying_price'])-price

def first(rows, types):
    return next((r for r in rows if r.get('event_type') in types), None)

def one_trade(entry, segment):
    rescue=first(segment, {'CAP20_RESCUE_TRIGGERED','CAP20_SHADOW_EXIT'})
    terminal=first(segment, {'STRUCTURAL_TERMINAL'})
    # Current policy is CAP20-only, no second leg. Never mark an unresolved
    # session at an invented end-of-day price.
    actual=rescue or terminal
    if actual is None or points(entry,actual) is None: return None
    degrade=first(segment, {'DEGRADED_STARTED'})
    # This is precisely the existing first eligible rebreak that CAP20 rejects
    # when it occurs above +20. At <=+20, rescue itself is the baseline exit.
    rebreak=first(segment, {'CAP20_RESCUE_TRIGGERED','CAP20_SHADOW_EXIT'}) or next(
        (r for r in segment if r.get('event_type')=='CAP20_CHECK'
         and r.get('reason')=='CAP20_FIRST_REBREAK_ABOVE_20_NO_RESCUE'),None)
    policy={'CAP20_ONLY':actual,'DEGRADED_EXIT':degrade or actual,
            'FIRST_ELIGIBLE_REBREAK_EXIT':rebreak or actual}
    # No candidate can exit after the baseline CAP20 rescue or terminal.
    cutoff=datetime.fromisoformat(actual['event_timestamp'])
    for k,r in list(policy.items()):
        if datetime.fromisoformat(r['event_timestamp'])>cutoff or points(entry,r) is None:
            policy[k]=actual
    return {'family':entry['family'], 'entry':entry['event_timestamp'],
            'baseline_event':actual['event_type'],
            'degrade_triggered':policy['DEGRADED_EXIT'] is not actual,
            'rebreak_triggered':policy['FIRST_ELIGIBLE_REBREAK_EXIT'] is not actual,
            'points':{k:points(entry,r) for k,r in policy.items()},
            'exit':{k:r['event_timestamp'] for k,r in policy.items()}}

def stats(values):
    return {'n':len(values),'sum':round(sum(values),2),
            'mean':round(statistics.mean(values),2) if values else None,
            'median':round(statistics.median(values),2) if values else None,
            'positive':sum(v>0 for v in values)}

def report(rows,label):
    print('\n'+label, 'matched completed:',len(rows),
          'degraded exits:',sum(r['degrade_triggered'] for r in rows),
          'first rebreak exits:',sum(r['rebreak_triggered'] for r in rows))
    for policy in ('CAP20_ONLY','DEGRADED_EXIT','FIRST_ELIGIBLE_REBREAK_EXIT'):
        s=stats([r['points'][policy] for r in rows]);
        delta=stats([r['points'][policy]-r['points']['CAP20_ONLY'] for r in rows])
        print(policy, s, 'delta versus CAP20-only:',delta)
    for policy,flag in (('DEGRADED_EXIT','degrade_triggered'),
                        ('FIRST_ELIGIBLE_REBREAK_EXIT','rebreak_triggered')):
        triggered=[r for r in rows if r[flag]]
        print('  changed-only',policy,'n',len(triggered),'delta',
              stats([r['points'][policy]-r['points']['CAP20_ONLY'] for r in triggered]))

def main():
    for p in (V55,V52,CANON,V57):
        if not p.is_file(): raise SystemExit(f'Missing frozen research script: {p}')
    v55=load(V55,'v55_exit_research');v52=load(V52,'v52_exit_research')
    canon=load(CANON,'canon_exit_research');v57=load(V57,'v57_exit_research')
    rows=[]; unresolved=Counter(); total_sessions=0
    for block in v52.BLOCKS:
        u,fut,_=v55.load_block(block,v52,canon)
        days=sorted(set(u)&set(fut));total_sessions+=len(days)
        owners=Counter(); block_entries=0
        for day in days:
            audit,_,_=v57.replay_session(day,u[day],fut[day])
            for event in audit:
                if event.get('event_type')=='BOUNDARY_CLASSIFIED': owners[str(event.get('result'))]+=1
            entries=[(i,r) for i,r in enumerate(audit) if r.get('event_type') in ('B_ENTRY','E_ENTRY')]
            block_entries+=len(entries)
            for j,(i,entry) in enumerate(entries):
                end=entries[j+1][0] if j+1<len(entries) else len(audit)
                result=one_trade(entry,audit[i:end])
                if result is None: unresolved[entry['family']]+=1
                else: rows.append(result)
        got={k:owners[k] for k in ('E','B','OTHER_FRESH_A')}
        if got != EXPECTED[block['name']]:
            raise SystemExit(f'STOP ownership parity {block["name"]}: {got}')
        print(block['name'],'sessions',len(days),'entries',block_entries,'ownership PASS',flush=True)
    if total_sessions!=480: raise SystemExit(f'STOP expected 480 sessions, got {total_sessions}')
    print('Unresolved without exact CAP20/terminal (excluded):',dict(unresolved))
    for label,subset in [('B',[r for r in rows if r['family']=='B']),
                         ('E',[r for r in rows if r['family']=='E']),('B+E',rows)]:
        report(subset,label)
    print('\nExploratory close-to-close underlying points only. No option P&L or execution.')

if __name__=='__main__': main()
