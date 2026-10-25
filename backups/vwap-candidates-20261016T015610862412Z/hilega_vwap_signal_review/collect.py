"""Independent GET-only VWAP annotation. Does not import trading workers."""
from __future__ import annotations
import argparse
import csv
import fcntl
import json
import math
import os
import time
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')


def dt(value):
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('TIMEZONE_REQUIRED')
    return result.astimezone(IST)


def vwap_at(candles, at):
    """Require every 5m candle from 09:15 through the last available boundary."""
    start = at.replace(hour=9, minute=15, second=0, microsecond=0)
    eligible = {}
    for raw in candles:
        ts = dt(raw[0])
        if ts.date() != at.date() or ts < start or ts+timedelta(minutes=5) > at:
            continue
        if ts in eligible:
            raise ValueError('DUPLICATE_FUTURES_CANDLE')
        h, l, close, volume = map(float, (raw[2], raw[3], raw[4], raw[5]))
        if not all(math.isfinite(v) for v in (h,l,close,volume)) or min(h,l,close)<=0 or volume<0 or not l<=close<=h:
            raise ValueError('INVALID_FUTURES_OHLCV')
        eligible[ts] = (h,l,close,volume)
    expected = []
    ts = start
    while ts+timedelta(minutes=5) <= at:
        expected.append(ts); ts += timedelta(minutes=5)
    if not expected or set(eligible) != set(expected):
        raise ValueError('INCOMPLETE_FUTURES_SESSION_PATH')
    pv = sum((h+l+c)/3*v for h,l,c,v in eligible.values())
    volume = sum(r[3] for r in eligible.values())
    if volume <= 0:
        raise ValueError('ZERO_CUMULATIVE_VOLUME')
    value = pv/volume
    last = expected[-1]
    close = eligible[last][2]
    distance = close-value
    return dict(vwap=value, futures_close=close, distance_points=distance,
                price_position='ABOVE' if distance>0 else 'BELOW' if distance<0 else 'AT',
                candle_start=last.isoformat(), candle_available_at=(last+timedelta(minutes=5)).isoformat(),
                age_at_signal_seconds=(at-last-timedelta(minutes=5)).total_seconds(),
                cumulative_volume=volume, candle_count=len(expected),
                basis='NIFTY_FUTURES_SESSION_5M_TYPICAL_PRICE_PROXY')


def signals(path, day):
    groups = {}
    exits = {}
    with path.open() as stream:
        for line in stream:
            if not line.endswith('\n'):
                continue  # An immutable audit record may still be getting appended.
            r = json.loads(line); p = r.get('payload') or {}
            at = p.get('decision_timestamp') or p.get('cutoff_timestamp')
            if not at or at[:10] != day or p.get('strategy_id') != 'HILEGA_V2_ALIGNMENT_DUAL_EXIT':
                continue
            if r.get('stage') not in ('DIRECTIONAL_DECISION','DIRECTIONAL_SESSION_CUTOFF'):
                continue
            live = r.get('status') == 'PROCESSED' and p.get('reconstructed') is not True
            for event in p.get('event_details') or []:
                if event.get('exit_reason'):
                    key = event['entry_time']
                    if key not in exits or (live and not exits[key][0]):
                        exits[key] = (live, event)
            items = [dict(kind='SETUP', direction=s['direction'], source=s['source'],
                          candle_label=p.get('bar_timestamp')) for s in p.get('setup_attempts') or []]
            for event in p.get('event_details') or []:
                if event['event_type'].startswith('ENTRY'):
                    items.append(dict(kind='CONFIRMED_ENTRY', direction='BEARISH' if 'BEARISH' in event['event_type'] else 'BULLISH',
                                      source=event['event_type'], entry_time=event['entry_time'],
                                      entry_price=event['entry_price'], candle_label=p.get('bar_timestamp')))
            if not items:
                owner = p.get('trade_owner_after')
                if owner not in ('BULLISH', 'BEARISH'):
                    owner = p.get('trade_owner_before')
                items.append(dict(kind='DECISION_CHECKPOINT',
                                  direction=owner if owner in ('BULLISH', 'BEARISH') else 'NONE',
                                  source=r['stage'], candle_label=p.get('bar_timestamp')))
            for item in items:
                key = (at, item['kind'], item['direction'], item['source'])
                if key not in groups or (live and not groups[key][0]):
                    groups[key] = (live, dict(item, signal_time=at, nifty_reference_price=p.get('nifty_close'),
                                             strategy_version=p.get('strategy_version'), sequence=r.get('sequence'),
                                             audit_basis='PROCESSED' if live else 'RECOVERED'))
    result = []
    for _, item in groups.values():
        event = exits.get(item.get('entry_time'), (None,None))[1]
        item['trade_points'] = event.get('points') if event else None
        item['exit_reason'] = event.get('exit_reason') if event else None
        result.append(item)
    return sorted(result, key=lambda r:(r['signal_time'],r['kind'],r['direction']))


def collect(args):
    from dotenv import load_dotenv
    from market_lab.upstox_live_futures_v1 import UpstoxLiveFuturesGatewayV1
    load_dotenv()
    token = os.environ.get('UPSTOX_ACCESS_TOKEN')
    if not token:
        raise ValueError('UPSTOX_ACCESS_TOKEN_MISSING')
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    gateway = UpstoxLiveFuturesGatewayV1(token)
    try:
        for day in args.dates:
            session = date.fromisoformat(day)
            candidates = signals(args.audit, day)
            if not candidates:
                continue
            try:
                # Active catalog only: fail closed for historical expired sessions.
                if session.year != datetime.now(IST).year or session.month != datetime.now(IST).month:
                    raise ValueError('HISTORICAL_CONTRACT_MANIFEST_REQUIRED')
                instrument = gateway.resolve_nifty_front_future(today=session)
                if instrument.expiry < session:
                    raise ValueError('CONTRACT_EXPIRED_BEFORE_SESSION')
                atomic_json(args.output/f'{day}-futures-contract.json', asdict(instrument))
                key = quote(instrument.instrument_key, safe='')
                if session==datetime.now(IST).date():
                    body = gateway._get(f'/v3/historical-candle/intraday/{key}/minutes/5')
                else:
                    body = gateway._get(f'/v3/historical-candle/{key}/minutes/5/{day}/{day}')
                candles = body.get('data',{}).get('candles',[])
                atomic_json(args.output/f'{day}-futures-ohlcv.json', body)
                for item in candidates:
                    row = dict(item, session_date=day, instrument_key=instrument.instrument_key,
                               collected_at=datetime.now(IST).isoformat(), reconstructed=True,
                               evidence_type='RECONSTRUCTED_FROM_COMPLETED_FUTURES_CANDLES')
                    try:
                        row.update(vwap_at(candles,dt(item['signal_time'])),status='AVAILABLE')
                        row['direction_agrees_with_vwap'] = row['price_position']==('ABOVE' if item['direction']=='BULLISH' else 'BELOW') if item['direction']!='NONE' else None
                    except (ValueError,TypeError,KeyError,IndexError) as exc:
                        row.update(status='UNAVAILABLE', reason=str(exc) if isinstance(exc,ValueError) and str(exc).replace('_','').isupper() else 'INVALID_CANDLE_DATA')
                    rows.append(row)
            except Exception as exc:
                rows.extend(dict(item, session_date=day, status='UNAVAILABLE', reason=type(exc).__name__) for item in candidates)
    finally:
        gateway.close()
    report = dict(observation_only=True, entry_filter_enabled=False, rows=rows,
                  warning='Futures close compared to futures candle VWAP proxy; not index VWAP. Completed 5m data only; historical retrieval is reconstructed evidence, not a snapshot saved live.')
    temporary=args.output/'report.tmp'
    temporary.write_text(json.dumps(report,indent=2)+'\n');os.replace(temporary,args.output/'report.json')
    fields=['session_date','kind','direction','signal_time','candle_label','source','nifty_reference_price','futures_close','vwap','price_position','distance_points','direction_agrees_with_vwap','candle_available_at','age_at_signal_seconds','trade_points','exit_reason','status','reason']
    with (args.output/'signals.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    # Append first available observation per signal; recovered errors may retry.
    journal=args.output/'signal-vwap-observations.jsonl'
    seen=set()
    if journal.exists():
        with journal.open() as f:
            for line in f:
                r=json.loads(line);seen.add((r['signal_time'],r['kind'],r['direction'],r['source']))
    with journal.open('a') as f:
        for row in rows:
            identity=(row['signal_time'],row['kind'],row['direction'],row['source'])
            if row['status']=='AVAILABLE' and identity not in seen:
                f.write(json.dumps(row)+'\n');seen.add(identity)
        f.flush();os.fsync(f.fileno())
    print(json.dumps(dict(status='COLLECTED',signals=len(rows),available=sum(r['status']=='AVAILABLE' for r in rows),report=str(args.output/'report.json'))))


def atomic_json(path, payload):
    temporary = path.with_suffix(path.suffix+'.tmp')
    with temporary.open('w') as stream:
        json.dump(payload, stream, default=str, indent=2)
        stream.flush();os.fsync(stream.fileno())
    os.replace(temporary, path)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit',type=Path,default=Path('data/live-observation/hilega-directional-v1/step-audit.jsonl'))
    p.add_argument('--dates',nargs='+')
    p.add_argument('--output',type=Path,default=Path('data/research/hilega-vwap-oct13-14'))
    p.add_argument('--watch',action='store_true',help='Independent ongoing observation; no strategy changes')
    args=p.parse_args()
    fixed_dates=args.dates
    args.output.mkdir(parents=True,exist_ok=True)
    with (args.output/'collector.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while True:
            args.dates=fixed_dates or ([datetime.now(IST).date().isoformat()] if args.watch else ['2026-10-13','2026-10-14'])
            try:
                collect(args)
            except Exception as exc:
                if not args.watch:
                    raise SystemExit('COLLECTION_FAILED:'+type(exc).__name__) from None
                with (args.output/'errors.jsonl').open('a') as f:
                    f.write(json.dumps(dict(timestamp=datetime.now(IST).isoformat(),error_type=type(exc).__name__))+'\n')
            if not args.watch:
                break
            time.sleep(60)


if __name__=='__main__':main()
