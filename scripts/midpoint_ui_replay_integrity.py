#!/usr/bin/env python3
"""Read-only integrity audit of every materialized Midpoint historical UI session.

Usage: python scripts/midpoint_ui_replay_integrity.py
Reports missing 09:15–15:14 IST minutes, incomplete pairs and missing event bars.
Never fabricates candles, changes an audit, or calls a broker.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

IST=timezone(timedelta(hours=5,minutes=30))
ROOT=Path('data/historical-evidence/hilega-pcr-oi-support-research-v1/midpoint-ui-replay-v1')
EXPECTED=[time(9,15)]
EXPECTED=[(datetime.combine(date(2000,1,1),time(9,15),IST)+timedelta(minutes=i)).time() for i in range(360)]

def load(path):
    if not path.is_file():return []
    with path.open() as f:return [json.loads(x) for x in f if x.strip()]

def key(value, day):
    try:
        instant=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if instant.tzinfo is None:return None
        local=instant.astimezone(IST)
        if local.date().isoformat()!=day or local.second!=0 or local.microsecond!=0:return None
        return local.time().replace(tzinfo=None)
    except (ValueError, TypeError):return None

def inspect(session):
    day=session['session_date'];folder=ROOT/day
    minutes=load(folder/'minutes.jsonl');events=load(folder/'audit.jsonl')
    counts=Counter(key(m.get('timestamp'),day) for m in minutes)
    valid={t for t in counts if t is not None}
    expected=set(EXPECTED)
    missing=sorted(expected-valid)
    duplicates=sorted(t for t,n in counts.items() if t is not None and n>1)
    bad_pairs=[m for m in minutes if key(m.get('timestamp'),day) in expected and
               (m.get('underlying_close') is None or m.get('futures_close') is None or m.get('futures_vwap') is None)]
    missing_events=[e for e in events if key(e.get('event_timestamp'),day) not in valid]
    malformed=sum(key(m.get('timestamp'),day) is None for m in minutes)
    extra=sorted(valid-expected)
    return {'session_date':day,'source':session.get('source'),'minute_rows':len(minutes),
            'audit_events':len(events),'missing_count':len(missing),'missing_minutes':[t.strftime('%H:%M') for t in missing],
            'incomplete_pair_count':len(bad_pairs),
            'incomplete_pair_minutes':[str(m.get('timestamp',''))[11:16] for m in bad_pairs],
            'duplicate_minutes':[t.strftime('%H:%M') for t in duplicates],
            'malformed_timestamp_count':malformed,
            'outside_window_minutes':[t.strftime('%H:%M') for t in extra],
            'events_without_minute':[{'time':e.get('event_timestamp'),'event_type':e.get('event_type')} for e in missing_events],
            'manifest_minute_count':session.get('minute_count'),
            'manifest_count_mismatch':session.get('minute_count')!=len(minutes)}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--date',help='Inspect just one YYYY-MM-DD date')
    p.add_argument('--output',type=Path,default=Path('data/historical-evidence/midpoint-ui-replay-integrity.json'))
    args=p.parse_args()
    manifest=json.loads((ROOT/'manifest.json').read_text())
    sessions=manifest.get('sessions',[])
    if args.date:sessions=[s for s in sessions if s['session_date']==args.date]
    if args.date and not sessions:raise SystemExit('STOP date not displayed in Midpoint historical manifest')
    rows=[inspect(s) for s in sessions]
    issues=[r for r in rows if r['missing_count'] or r['incomplete_pair_count'] or r['duplicate_minutes'] or
            r['malformed_timestamp_count'] or r['events_without_minute'] or r['manifest_count_mismatch']]
    by_source={source:{'dates':sum(r['source']==source for r in rows),
                       'dates_with_issues':sum(r['source']==source for r in issues)}
               for source in sorted({str(r['source']) for r in rows})}
    report={'model':'MIDPOINT_UI_REPLAY_INTEGRITY_V1','expected_minutes':'09:15–15:14 IST, 360 exact minutes',
            'displayed_sessions':len(rows),'dates_with_issues':len(issues),
            'by_source':by_source,'sessions':rows}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2))
    print('Displayed sessions:',len(rows),'dates with issues:',len(issues),'by source:',by_source)
    for r in issues[:25]:
        print(r['session_date'],r['source'],'missing',r['missing_count'],
              'incomplete pairs',r['incomplete_pair_count'],'events without bar',len(r['events_without_minute']),
              'duplicates',len(r['duplicate_minutes']),'manifest mismatch',r['manifest_count_mismatch'])
    print('Full per-date report:',args.output)
    print('Read only; no market candles or audit events changed.')

if __name__=='__main__':main()
