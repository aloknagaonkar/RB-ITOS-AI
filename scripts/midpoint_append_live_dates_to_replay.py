#!/usr/bin/env python3
"""Materialize 2026-09-28/29 Midpoint replay from exact market candles and live audit.

Observation-only. Requires UPSTOX_ACCESS_TOKEN and the existing live audit.
Stops before publication if 360 complete minute pairs or live-audit price/VWAP
parity cannot be proved. Keeps the existing historical manifest sessions.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path

from dotenv import load_dotenv
from market_lab.domain import IST
from market_lab.midpoint_v2_nifty_futures_vwap_v1 import (
    _client, available_expiries, fetch_one_minute_candles, resolve_active_future,
)
from market_lab.midpoint_strategy.replay import load_audit_jsonl
from market_lab.upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1

ROOT=Path('data/historical-evidence/hilega-pcr-oi-support-research-v1/midpoint-ui-replay-v1')
AUDIT=Path('data/live-observation/midpoint-strategy-v1/audit.jsonl')
INDEX='NSE_INDEX|Nifty 50'
START=time(9,15)
END=time(15,14)


def minute_key(value):
    ts=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if ts.tzinfo is None:raise ValueError('AWARE_TIMESTAMP_REQUIRED')
    ts=ts.astimezone(IST)
    if ts.second or ts.microsecond:raise ValueError(f'EXACT_MINUTE_REQUIRED_{ts.isoformat()}')
    return ts


def normalize_index(rows, day):
    result={}
    for candle in rows:
        ts=minute_key(candle.timestamp)
        if ts.date()!=day or not START<=ts.time()<=END:continue
        if ts in result:raise ValueError('DUPLICATE_INDEX_MINUTE')
        result[ts]={'open':float(candle.open),'high':float(candle.high),
                    'low':float(candle.low),'close':float(candle.close)}
    return result


def normalize_futures(rows, day):
    by_ts={}
    for candle in rows:
        ts=minute_key(candle['timestamp'])
        if ts.date()!=day or not START<=ts.time()<=END:continue
        if ts in by_ts:raise ValueError('DUPLICATE_FUTURES_MINUTE')
        volume=candle.get('volume')
        if volume is None or float(volume)<=0:raise ValueError(f'FUTURES_VOLUME_MISSING_{ts.isoformat()}')
        by_ts[ts]={
            'open':float(candle['open']) if candle.get('open') is not None else None,
            'close':float(candle['close']),'volume':float(volume)
        }
    pv=volume_sum=0.0
    for ts in sorted(by_ts):
        f=by_ts[ts]
        pv+=f['close']*f['volume']
        volume_sum+=f['volume']
        f['vwap']=pv/volume_sum
    return by_ts


def exact_minutes(day,index,futures):
    expected=[datetime.combine(day,START,IST)+timedelta(minutes=i) for i in range(360)]
    if set(index)!=set(expected) or set(futures)!=set(expected):
        missing_index=[x.strftime('%H:%M') for x in expected if x not in index]
        missing_futures=[x.strftime('%H:%M') for x in expected if x not in futures]
        raise ValueError(f'EXACT_360_PAIR_REQUIRED {day} index_missing={missing_index[:10]} futures_missing={missing_futures[:10]}')
    return [{'session_date':day.isoformat(),'timestamp':ts.isoformat(),
             'underlying_open':index[ts]['open'],'underlying_high':index[ts]['high'],
             'underlying_low':index[ts]['low'],'underlying_close':index[ts]['close'],
             'futures_open':futures[ts]['open'],
             'futures_close':futures[ts]['close'],'futures_vwap':futures[ts]['vwap'],
             'futures_volume':futures[ts]['volume'],
             'data_status':'BOTH'} for ts in expected]


def audit_parity(day, audit_rows, index, futures):
    day_rows=[r for r in audit_rows if r.get('session_date')==day.isoformat()]
    if not day_rows:
        raise ValueError(f'LIVE_AUDIT_REQUIRED_{day}')
    rows=[]
    verified_price_rows=0
    differences=[]
    for row in day_rows:
        if row.get('observation_only') is not True or row.get('execution_enabled') is not False or row.get('paper_order_enabled') is not False or row.get('quantity') is not None:
            raise ValueError('LIVE_AUDIT_SAFETY_MISMATCH')
        ts=minute_key(row['event_timestamp'])
        # Historical Replay is deliberately the exact 360 completed candles
        # from 09:15 through 15:14.  Session-end bookkeeping stamped 15:15 or
        # later remains in the immutable live audit but is outside this replay
        # evidence window and therefore has no candle with which to prove
        # parity.  Never fabricate a 361st minute.
        if ts.date()!=day or not START<=ts.time()<=END:
            continue
        rows.append(row)
        if ts not in index or ts not in futures:
            raise ValueError(f'AUDIT_EVENT_MINUTE_UNAVAILABLE_{ts.isoformat()}')
        for field, source, tolerance in (
            ('underlying_price',index[ts]['close'],0.06),
            ('futures_price',futures[ts]['close'],0.06),
            ('futures_vwap',futures[ts]['vwap'],0.20),
        ):
            observed=row.get(field)
            if observed is not None and abs(float(observed)-source)>tolerance:
                differences.append({'event_timestamp':ts.isoformat(),'event_type':row['event_type'],
                                    'field':field,'live_audit':float(observed),
                                    'downloaded_candle':source,'delta':round(source-float(observed),6)})
            if field=='futures_price' and observed is not None:verified_price_rows+=1
    if not rows:raise ValueError(f'LIVE_AUDIT_IN_REPLAY_WINDOW_REQUIRED_{day}')
    if not verified_price_rows:raise ValueError(f'LIVE_FUTURES_PARITY_UNAVAILABLE_{day}')
    return rows,differences


def fetch_day(day, audit_rows, sources, expired_expiries, futures_client):
    today=datetime.now(IST).date()
    index_rows=(sources.nifty_intraday_1m() if day==today
                else sources.historical_candles(INDEX,day))
    contract=resolve_active_future(futures_client,day,expired_expiries)
    if day==today:
        raw=[{'timestamp':c.timestamp,'open':c.open,'close':c.close,'volume':c.volume}
             for c in sources.option_intraday_1m(contract.instrument_key)]
    else:
        raw=fetch_one_minute_candles(futures_client,contract,day)
    index=normalize_index(index_rows,day)
    futures=normalize_futures(raw,day)
    minutes=exact_minutes(day,index,futures)
    events,differences=audit_parity(day,audit_rows,index,futures)
    return minutes,events,contract,differences


def write_jsonl(path,rows):
    with path.open('w') as f:
        for row in rows:f.write(json.dumps(row,sort_keys=True,separators=(',',':'))+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dates',nargs='+',type=date.fromisoformat,default=[date(2026,9,28),date(2026,9,29)])
    p.add_argument('--accept-revised-candles',action='store_true',
                   help='Publish with audited live signal values and separately labelled downloaded minute candles')
    args=p.parse_args()
    days=sorted(set(args.dates))
    if any(d>datetime.now(IST).date() for d in days):raise SystemExit('STOP future session')
    load_dotenv('.env')
    token=os.getenv('UPSTOX_ACCESS_TOKEN')
    if not token:raise SystemExit('STOP UPSTOX_ACCESS_TOKEN missing')
    manifest_path=ROOT/'manifest.json'
    if not manifest_path.exists():raise SystemExit('STOP historical replay manifest missing')
    manifest=json.loads(manifest_path.read_text())
    indexed={r['session_date']:r for r in manifest['sessions']}
    if any(d.isoformat() in indexed or (ROOT/d.isoformat()).exists() for d in days):
        raise SystemExit('STOP one of these dates already exists; no overwrite')
    live_rows=load_audit_jsonl(AUDIT)
    staged=[]
    sources=UpstoxLiveShadowSourcesV1(token)
    try:
        with _client() as client:
            expiries=available_expiries(client)
            for day in days:
                minutes,events,contract,differences=fetch_day(day,live_rows,sources,expiries,client)
                staged.append((day,minutes,events,contract,differences))
                print('VALIDATED',day,'minutes',len(minutes),'events',len(events),
                      'futures',contract.instrument_key,'expiry',contract.expiry)
                for field in ('underlying_price','futures_price','futures_vwap'):
                    mismatches=[x for x in differences if x['field']==field]
                    print('SOURCE COMPARISON',day,field,'differences',len(mismatches),
                          'max_abs_delta',round(max((abs(x['delta']) for x in mismatches),default=0),5))
    finally:
        sources.close()
    all_differences=sum(len(x[4]) for x in staged)
    if all_differences and not args.accept_revised_candles:
        raise SystemExit('STOP revised candles differ from live audit at '
                         f'{all_differences} event fields. No dates published. '
                         'Review SOURCE COMPARISON and rerun with --accept-revised-candles '
                         'to keep both values with provenance.')
    # No writes until every requested session has passed source and audit parity.
    ROOT.mkdir(parents=True,exist_ok=True)
    for day,minutes,events,contract,differences in staged:
        folder=ROOT/day.isoformat()
        folder.mkdir(exist_ok=False)
        write_jsonl(folder/'minutes.jsonl',minutes)
        write_jsonl(folder/'audit.jsonl',events)
        metadata={'session_date':day.isoformat(),'block':f'LIVE_AUDIT_RECENT_{day:%Y-%m}',
                  'event_count':len(events),'minute_count':360,
                  'first_minute':minutes[0]['timestamp'],'last_minute':minutes[-1]['timestamp'],
                  'source':'LIVE_AUDIT_WITH_DOWNLOADED_CANDLES',
                  'minute_source':'UPSTOX_EXACT_1M_CLOSE_VOLUME_VWAP',
                  'signal_value_source':'ORIGINAL_LIVE_AUDIT',
                  'source_comparison_status':'REVISED_CANDLES' if differences else 'EXACT_PARITY',
                  'source_differences':differences,
                  'futures_instrument_key':contract.instrument_key,
                  'futures_expiry':contract.expiry.isoformat(),
                  'observation_only':True,'execution_enabled':False,
                  'paper_order_enabled':False,'quantity':None}
        (folder/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
        indexed[day.isoformat()]={k:metadata[k] for k in ('session_date','block','event_count','minute_count','first_minute','last_minute','source')}
        indexed[day.isoformat()]['status']='AVAILABLE'
    manifest['sessions']=sorted(indexed.values(),key=lambda r:r['session_date'],reverse=True)
    manifest['session_count']=len(indexed)
    with tempfile.NamedTemporaryFile(mode='w',dir=ROOT,prefix='manifest.',suffix='.tmp',delete=False) as f:
        json.dump(manifest,f,indent=2)
        temporary=Path(f.name)
    temporary.replace(manifest_path)
    print('PUBLISHED',', '.join(str(d) for d in days),'manifest sessions',len(indexed))
    print('Observation only; live audit and workers untouched.')

if __name__=='__main__':main()
