#!/usr/bin/env python3
"""Frozen, read-only forward B/E exit comparison from 2026-09-30 onward.

Run after a captured session. Uses immutable Midpoint audit and optional exact
five-contract tape. No orders, strategy mutation, threshold search, or fills.
"""
from __future__ import annotations
import json
import argparse
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

START = '2026-09-30'  # Sep 29 and the 480-session cohort are development evidence.
ROOT = Path('data/live-observation/midpoint-strategy-v1')
AUDIT = ROOT / 'audit.jsonl'
TAPES = ROOT / 'option-observation'
ENTRY = {'B_ENTRY','E_ENTRY'}
BASELINE = {'CAP20_RESCUE_TRIGGERED','CAP20_SHADOW_EXIT','STRUCTURAL_TERMINAL'}
VERSION = 'MIDPOINT_BE_FORWARD_EXIT_OBSERVATION_V1'


def _dt(value): return datetime.fromisoformat(value)


def _points(entry, event):
    price=event.get('underlying_price')
    if price is None:return None
    return (float(price)-float(entry['underlying_price'])) * (1 if entry['direction']=='BULLISH' else -1)


def _first(events, types):
    return next((x for x in events if x.get('event_type') in types),None)


def _option(tape, event):
    if not tape:return {'status':'TAPE_UNAVAILABLE','legs':[]}
    if tape.get('entry_event_id')!=event['entry_event_id']:
        raise ValueError('OPTION_TAPE_ENTRY_MISMATCH')
    boundary=tape['entry_boundary']
    exit_at=(_dt(event['event_timestamp'])+timedelta(minutes=1)).isoformat()
    legs=[]
    for leg in tape['legs']:
        by_ts={row['timestamp']:row for row in leg['minutes']}
        a,b=by_ts.get(boundary),by_ts.get(exit_at)
        result={'relation_to_atm':leg['relation_to_atm'],'instrument_key':leg['instrument_key'],
                'entry_premium':float(a['open']) if a else None,
                'exit_premium':float(b['open']) if b else None}
        result['pnl_points']=round(result['exit_premium']-result['entry_premium'],4) if a and b else None
        result['status']='AVAILABLE' if result['pnl_points'] is not None else 'EXACT_MINUTE_UNAVAILABLE'
        legs.append(result)
    status='AVAILABLE' if len(legs)==5 and all(x['status']=='AVAILABLE' for x in legs) else 'UNAVAILABLE'
    return {'status':status,'exit_option_minute':exit_at,'legs':legs}


def evaluate(entry, segment, tape):
    if entry['family'] not in ('B','E') or entry.get('underlying_price') is None:
        raise ValueError('B_OR_E_ENTRY_WITH_SPOT_REQUIRED')
    actual=_first(segment, BASELINE)
    if not actual or _points(entry,actual) is None:
        return {'session_date':entry['session_date'],'family':entry['family'],
                'entry_event_id':entry['event_id'],'entry_timestamp':entry['event_timestamp'],
                'status':'UNRESOLVED_NO_EXACT_EXIT'}
    cutoff=_dt(actual['event_timestamp'])
    earlier=lambda r:r is not None and _dt(r['event_timestamp'])<=cutoff and _points(entry,r) is not None
    degrade=_first(segment, {'DEGRADED_STARTED'})
    rebreak=next((r for r in segment if r.get('event_type')=='CAP20_CHECK'
                  and r.get('reason')=='CAP20_FIRST_REBREAK_ABOVE_20_NO_RESCUE'),None)
    if actual['event_type'] in ('CAP20_RESCUE_TRIGGERED','CAP20_SHADOW_EXIT'):
        if not earlier(rebreak) or _dt(actual['event_timestamp'])<=_dt(rebreak['event_timestamp']):
            rebreak=actual
    candidates={'CAP20_ONLY':actual,'DEGRADED_EXIT':degrade if earlier(degrade) else actual,
                'FIRST_ELIGIBLE_REBREAK_EXIT':rebreak if earlier(rebreak) else actual}
    row={'session_date':entry['session_date'],'family':entry['family'],
         'entry_event_id':entry['event_id'],'entry_timestamp':entry['event_timestamp'],
         'status':'COMPLETED','policies':{}}
    for name,ev in candidates.items():
        evidence=dict(ev);evidence['entry_event_id']=entry['event_id']
        row['policies'][name]={'event_timestamp':ev['event_timestamp'],'event_type':ev['event_type'],
            'underlying_points':round(_points(entry,ev),4),'option':_option(tape,evidence)}
    return row


def run(audit=AUDIT, tapes=TAPES, start=START):
    if not audit.is_file():return {'model':VERSION,'start_session':start,'status':'NO_AUDIT','trades':[]}
    all_rows=[json.loads(s) for s in audit.read_text().splitlines() if s.strip()]
    rows=[r for r in all_rows if r.get('session_date','')>=start]
    ids=[r['event_id'] for r in rows]
    if len(ids)!=len(set(ids)):raise ValueError('DUPLICATE_AUDIT_EVENT_ID')
    if any(r.get('observation_only') is not True or r.get('execution_enabled') is not False
           or r.get('paper_order_enabled') is not False or r.get('quantity') is not None for r in rows):
        raise ValueError('AUDIT_SAFETY_VIOLATION')
    sessions=sorted({r['session_date'] for r in rows})
    trades=[]
    for day in sessions:
        events=sorted((r for r in rows if r['session_date']==day),key=lambda r:r['event_timestamp'])
        entries=[(i,r) for i,r in enumerate(events) if r.get('event_type') in ENTRY]
        tape_path=tapes/f'{day}.json'
        available=json.loads(tape_path.read_text())['tapes'] if tape_path.exists() else []
        tapes_by_id={t['entry_event_id']:t for t in available}
        if len(tapes_by_id)!=len(available):raise ValueError('DUPLICATE_OPTION_TAPE_ENTRY')
        for j,(i,entry) in enumerate(entries):
            stop=entries[j+1][0] if j+1<len(entries) else len(events)
            trades.append(evaluate(entry,events[i:stop],tapes_by_id.get(entry['event_id'])))
    completed=[t for t in trades if t['status']=='COMPLETED']
    summary={}
    for family in ('B','E','B+E'):
        group=[t for t in completed if family=='B+E' or t['family']==family]
        item={'completed':len(group),'unresolved':sum(t['status']!='COMPLETED' and (family=='B+E' or t['family']==family) for t in trades)}
        for name in ('CAP20_ONLY','DEGRADED_EXIT','FIRST_ELIGIBLE_REBREAK_EXIT'):
            p=[t['policies'][name] for t in group]
            delta=[x['underlying_points']-t['policies']['CAP20_ONLY']['underlying_points'] for x,t in zip(p,group)]
            item[name]={'sum_underlying_points':round(sum(x['underlying_points'] for x in p),2),
                        'positive':sum(x['underlying_points']>0 for x in p),
                        'delta_vs_baseline':round(sum(delta),2),
                        'changed_exits':sum(x['event_timestamp']!=t['policies']['CAP20_ONLY']['event_timestamp'] for x,t in zip(p,group)),
                        'five_leg_option_complete':sum(x['option']['status']=='AVAILABLE' for x in p)}
        summary[family]=item
    return {'model':VERSION,'start_session':start,
            'evidence_cohort':'FORWARD_FROM_2026_09_30' if start>=START else 'DEVELOPMENT_INCLUDES_KNOWN_SESSIONS',
            'status':'OBSERVATION_ONLY',
            'session_dates':sessions,'entry_count':len(trades),'summary':summary,'trades':trades,
            'limitations':['Development dates are not independent forward validation','Unresolved trades excluded from completed totals',
                           'Option points are independent contracts; no quantity, spreads, charges, or fills']}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start',default=START,help='ISO session date; dates before 2026-09-30 are labeled development evidence')
    args=parser.parse_args()
    datetime.fromisoformat(args.start)
    report=run(start=args.start)
    print('MODEL',report['model'],'cohort',report.get('evidence_cohort','NONE'),
          'sessions',report.get('session_dates',[]),'entries',report.get('entry_count',0))
    print(json.dumps(report.get('summary',{}),indent=2))
    for t in report['trades']:
        print(t['session_date'],t['family'],t['entry_timestamp'],t['status'],
              {k:(v['event_timestamp'],v['underlying_points'],v['option']['status']) for k,v in t.get('policies',{}).items()})
    print('Read only: live decisions, audit, option tapes, orders and quantity untouched.')
