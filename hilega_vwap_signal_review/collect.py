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
    selected = {}
    with path.open() as stream:
        for line in stream:
            if not line.endswith('\n'):
                continue
            r = json.loads(line)
            p = r.get('payload') or {}
            at = p.get('decision_timestamp') or p.get('cutoff_timestamp')
            if not at or at[:10] != day or p.get('strategy_id') != 'HILEGA_V2_ALIGNMENT_DUAL_EXIT':
                continue
            if r.get('stage') not in ('DIRECTIONAL_DECISION', 'DIRECTIONAL_SESSION_CUTOFF'):
                continue
            if r.get('status') not in ('PROCESSED', 'RECOVERED'):
                continue
            key = (dt(at), r['stage'])
            rank = 2 if r.get('status') == 'PROCESSED' and p.get('reconstructed') is not True else 1
            prior = selected.get(key)
            if prior is None or rank > prior[0]:
                selected[key] = (rank, r)
    # Select the authoritative payload before interpreting its state flags.
    # Otherwise recovered-only candidates could leak into a processed checkpoint.
    for _, r in selected.values():
        p = r.get('payload') or {}
        at = p.get('decision_timestamp') or p.get('cutoff_timestamp')
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
        has_signal_items = bool(items)
        context = {key: p.get(key) for key in (
            'bullish_armed', 'bearish_armed', 'bullish_state', 'bearish_state',
            'trade_owner_before', 'trade_owner_after')}
        # An armed candidate is independent of the active trade owner.
        # Preserve both sides when both flags are explicitly true.
        for direction, flag in (('BULLISH', 'bullish_armed'), ('BEARISH', 'bearish_armed')):
            if p.get(flag) is True and not any(item['direction'] == direction for item in items):
                items.append(dict(kind='ARMED_CANDIDATE', direction=direction,
                                  context_type='ARMED_CANDIDATE', context_evidence=context,
                                  context_version='HILEGA_VWAP_DIRECTION_CONTEXT_V2',
                                  source=r['stage'], candle_label=p.get('bar_timestamp')))
        if not has_signal_items:
            after = p.get('trade_owner_after')
            before = p.get('trade_owner_before')
            owner = after if after in ('BULLISH', 'BEARISH') else before
            if owner in ('BULLISH', 'BEARISH') or not items:
                items.append(dict(kind='DECISION_CHECKPOINT',
                                  direction=owner if owner in ('BULLISH', 'BEARISH') else 'NONE',
                                  context_type='ACTIVE_POSITION' if after in ('BULLISH', 'BEARISH') else
                                               'EXITING_POSITION' if before in ('BULLISH', 'BEARISH') else 'NO_DIRECTION',
                                  context_evidence=context, context_version='HILEGA_VWAP_DIRECTION_CONTEXT_V2',
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


def repair_context(args):
    """Append missing arm context using exact already-recorded VWAP evidence.

    No provider calls, price substitution, or journal rewriting. Run while
    holding the same collector lock used by normal collection.
    """
    journal=args.output/'signal-vwap-observations.jsonl'
    if not journal.exists():
        raise ValueError('RECORDED_VWAP_JOURNAL_REQUIRED')
    rows=[]
    with journal.open() as stream:
        for line in stream:
            if line.endswith('\n'):
                rows.append(json.loads(line))
    seen={(r.get('signal_time'),r.get('kind'),r.get('direction'),r.get('source'))
          for r in rows if r.get('status')=='AVAILABLE'}
    market={}
    for row in rows:
        try:
            if row.get('status')!='AVAILABLE' or row.get('basis')!='NIFTY_FUTURES_SESSION_5M_TYPICAL_PRICE_PROXY':
                continue
            at=dt(row['signal_time']);available=dt(row['candle_available_at'])
            if at.date()!=available.date() or not 0<=(at-available).total_seconds()<300:
                continue
            if not all(isinstance(row.get(k),(int,float)) and not isinstance(row.get(k),bool)
                       and math.isfinite(row[k]) for k in ('vwap','futures_close','distance_points')):
                continue
            if min(row['vwap'],row['futures_close'])<=0 or not row.get('instrument_key'):
                continue
            if abs(row['futures_close']-row['vwap']-row['distance_points'])>1e-6:
                continue
            market.setdefault(at,[]).append(row)
        except (ValueError,TypeError,KeyError):
            continue
    appended=[];skipped=[]
    for day in args.dates:
        for item in signals(args.audit,day):
            if item['kind']!='ARMED_CANDIDATE':continue
            identity=(item['signal_time'],item['kind'],item['direction'],item['source'])
            if identity in seen:continue
            candidates=market.get(dt(item['signal_time']),[])
            keys={row['instrument_key'] for row in candidates}
            if len(keys)!=1:
                skipped.append(dict(signal_time=item['signal_time'],direction=item['direction'],
                                    reason='NO_EXACT_RECORDED_VWAP' if not keys else 'AMBIGUOUS_RECORDED_FUTURES_CONTRACT'))
                continue
            source=candidates[0]
            row=dict(source,**item)
            distance=row['distance_points']
            row['price_position']='ABOVE' if distance>0 else 'BELOW' if distance<0 else 'AT'
            row.update(direction_agrees_with_vwap=row['price_position']==('ABOVE' if item['direction']=='BULLISH' else 'BELOW'),
                       context_repaired_at=datetime.now(IST).isoformat(),reconstructed=True,
                       evidence_type='ARM_CONTEXT_REPAIR_FROM_RECORDED_VWAP',
                       vwap_source_identity={key:source.get(key) for key in ('signal_time','kind','direction','source','collected_at')})
            appended.append(row);seen.add(identity)
    with journal.open('a') as stream:
        for row in appended:stream.write(json.dumps(row)+'\n')
        stream.flush();os.fsync(stream.fileno())
    print(json.dumps(dict(status='CONTEXT_REPAIRED',appended=len(appended),skipped=skipped,
                         prices_refetched=False,orders_sent=False,observation_only=True)))


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
    p.add_argument('--repair-context',action='store_true',help='Append missing candidate context using recorded VWAP; no network calls')
    args=p.parse_args()
    if args.repair_context and (args.watch or not args.dates):
        p.error('--repair-context requires explicit --dates and cannot use --watch')
    fixed_dates=args.dates
    args.output.mkdir(parents=True,exist_ok=True)
    with (args.output/'collector.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.repair_context:
            repair_context(args)
            return
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
