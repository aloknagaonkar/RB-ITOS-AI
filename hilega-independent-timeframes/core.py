"""Offline cadence comparison. No orders, services, or installed source writes."""
import argparse
from datetime import date, datetime, time, timedelta
import hashlib
import importlib
import json
from pathlib import Path
import sys
import types
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path.cwd() / 'backend'))
from market_lab import hilega_combined_policy_v1 as policy5
from market_lab import hilega_v2_alignment_replay_v1 as legacy5
from market_lab.hilega_milega_strategy_v1 import FiveMinuteBar
from market_lab.domain import IST

def read_inputs(path):
    with ZipFile(path) as archive:
        warm = []
        for name in sorted(archive.namelist()):
            if name.startswith('candles/') and name.endswith('.json'):
                data = json.loads(archive.read(name))
                if data.get('candles'):
                    warm.append((Path(name).stem, data['candles']))
        return warm, json.loads(archive.read('today-audit.json'))

def aggregate(raw, day, interval, until):
    if interval not in (1,3,5):raise ValueError('INVALID_INTERVAL')
    validate_rows(raw,day)
    start = datetime.combine(date.fromisoformat(day), time(9,15), IST)
    by_time = {}
    for row in raw:
        at = datetime.fromisoformat(row['timestamp']).astimezone(IST)
        if at in by_time:
            raise ValueError('DUPLICATE_MINUTE:' + at.isoformat())
        by_time[at] = row
    result = []
    label = start
    while label + timedelta(minutes=interval) <= until:
        rows = []
        for offset in range(interval):
            at = label + timedelta(minutes=offset)
            if at not in by_time:
                raise ValueError('MISSING_MINUTE:' + at.isoformat())
            rows.append(by_time[at])
        result.append(FiveMinuteBar(label, float(rows[0]['open']),
            max(float(r['high']) for r in rows), min(float(r['low']) for r in rows),
            float(rows[-1]['close']), sum(float(r.get('volume') or 0) for r in rows)))
        label += timedelta(minutes=interval)
    return result

def run(policy, legacy, warm, raw, day, interval, until, target_bars=None):
    c = legacy.ExitFirstCanonical()
    tracker = policy.PriceFrames()
    count = 0
    for d, rows in warm:
        if d >= day:
            continue
        end = datetime.combine(date.fromisoformat(d), time(15,30), IST)
        for bar in aggregate(rows, d, interval, end):
            c.on_bar(bar)
            tracker.seed(bar)
        count += 1
    if count < 20:
        raise ValueError('INSUFFICIENT_WARMUP')
    opening = c.bullish.previous_indicators
    c.bullish.session = legacy.SessionState(session_date=date.fromisoformat(day))
    c.bearish.session = legacy.BearishSessionState(session_date=date.fromisoformat(day))
    for engine in (c.bullish,c.bearish):
        engine.previous_indicators = None
        engine.previous_bar = None
    c.trade_owner = 'NONE'
    c.session_date = date.fromisoformat(day)
    gate = policy.make_gate(tracker.frames)
    closed, audit, active = [], [], None
    cutoff = datetime.combine(date.fromisoformat(day), time(14,55), IST)
    for bar in (aggregate(raw, day, interval, min(until, cutoff)) if target_bars is None else target_bars):
        reference = c.bullish.previous_indicators or opening
        result = policy.advance_boundary(c, gate, bar, reference, tracker)
        at = bar.ts + timedelta(minutes=interval)
        for event in result['exits']:
            if active is None:
                raise ValueError('EXIT_WITHOUT_ENTRY')
            active.update(exit_time=at.isoformat(), exit_price=event.price,
                          points=event.points, exit_reason=event.exit_reason)
            closed.append(active)
            active = None
        for event in result['entries']:
            if active is not None:
                raise ValueError('OVERLAPPING_POSITION')
            active = dict(direction=legacy.direction(event), entry_time=at.isoformat(),
                entry_price=event.entry_price, setup=event.details['wma_gap']['signal_available_at'],
                qualified=event.details.get('qualified_signal_time'),
                entry_evidence=event.details.get('combined_entry'))
        audit.append(dict(time=at.isoformat(), frame=result['frame'],
            checks=result['checks'], setups=result['setups'],
            pending={k:v['available'].isoformat() for k,v in gate.pending.items()},
            owner=gate.owner, entries=[dict(direction=legacy.direction(e),time=at.isoformat(),price=e.entry_price) for e in result['entries']],
            exits=[dict(direction=legacy.direction(e),time=at.isoformat(),price=e.price) for e in result['exits']],
            opposite_confirmation=result.get('opposite_confirmation'),
            policy_events=result['policy_events'], exit_validation=result['exit_validation']))
    if active is not None and until >= cutoff:
        row = next((r for r in raw if datetime.fromisoformat(r['timestamp']) == cutoff), None)
        if row is None:
            raise ValueError('CUTOFF_OPEN_REQUIRED')
        price = float(row['open'])
        active.update(exit_time=cutoff.isoformat(), exit_price=price,
            points=(price-active['entry_price'])*(1 if active['direction']=='BULLISH' else -1),
            exit_reason='SESSION_CUTOFF_1455')
        closed.append(active)
        active = None
    mark = next((float(r['close']) for r in raw
        if datetime.fromisoformat(r['timestamp']) == until-timedelta(minutes=1)), None)
    if mark is None:
        raise ValueError('COMMON_HORIZON_MARK_MISSING')
    if active:
        active.update(mark_time=until.isoformat(), mark_price=mark,
            unrealized_points=(mark-active['entry_price'])*(1 if active['direction']=='BULLISH' else -1))
    return dict(interval=interval, warmup_sessions=count, trades=closed,
        open_trade=active, audit=audit,
        closed_points=sum(t['points'] for t in closed))

def recorded_events(rows, until):
    seen, entries, exits = set(), [], []
    for row in rows:
        p = row.get('payload') or {}
        for event in p.get('event_details') or []:
            if not event.get('entry_time') or not event.get('event_time'):
                continue
            if datetime.fromisoformat(event['event_time']) > until:
                continue
            identity = (event['event_type'],event['event_time'],event['entry_time'])
            if identity in seen:
                continue
            seen.add(identity)
            (exits if event.get('exit_reason') else entries).append(event)
    return entries, exits

def validate_rows(raw, day, allow_outside=False):
    import math
    seen=set()
    for row in raw:
        stamp=datetime.fromisoformat(row['timestamp'])
        if stamp.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
        stamp=stamp.astimezone(IST)
        if stamp.date().isoformat()!=day:raise ValueError('SESSION_DATE_MISMATCH')
        if stamp.second or stamp.microsecond:raise ValueError('MINUTE_ALIGNMENT_REQUIRED')
        if not time(9,15)<=stamp.time()<time(15,30) and not allow_outside:
            raise ValueError('OUTSIDE_REGULAR_SESSION:'+day+':'+stamp.isoformat())
        if stamp in seen:raise ValueError('DUPLICATE_MINUTE:'+stamp.isoformat())
        seen.add(stamp)
        vals=[row.get(k) for k in ('open','high','low','close')]
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in vals):
            raise ValueError('INVALID_PRICE')
        o,h,l,c=vals
        if h<max(o,l,c) or l>min(o,h,c):raise ValueError('INVALID_OHLC')
        volume=row.get('volume')
        if volume is not None and (isinstance(volume,bool) or not isinstance(volume,(int,float)) or not math.isfinite(volume) or volume<0):raise ValueError('INVALID_VOLUME')
    return seen


def parity(result, records, until):
    """Require complete recorded boundaries, identical trades/direction and frames."""
    import math
    issues=[];saved={};event_map={};saw_cutoff=False
    day=until.date().isoformat()
    for row in records:
        p=row.get('payload') or {}
        at=p.get('decision_timestamp')
        if at and at.startswith(day) and datetime.fromisoformat(at)<=until:
            if row.get('stage')=='DIRECTIONAL_SESSION_CUTOFF':saw_cutoff=True
            if row.get('stage')=='DIRECTIONAL_DECISION':
                identity={k:p.get(k) for k in ('price_ema_frame','event_details','strategy_version')}
                if at in saved and saved[at]!=identity:issues.append('CONFLICTING_RECORDED_BOUNDARY:'+at)
                saved[at]=identity
        for e in p.get('event_details') or []:
            if not e.get('entry_time') or not e.get('event_time'):continue
            et=datetime.fromisoformat(e['event_time'])
            if et.date().isoformat()!=day or et>until:continue
            key=(e['event_type'],e['event_time'],e['entry_time'])
            identity={k:e.get(k) for k in ('event_type','event_time','entry_time','entry_price','price','points','exit_reason')}
            if key in event_map and event_map[key]!=identity:issues.append('CONFLICTING_EVENT:'+str(key))
            event_map[key]=identity
    expected_times=[];at=datetime.combine(until.date(),time(9,20),IST)
    while at<=until:
        expected_times.append(at.isoformat());at+=timedelta(minutes=5)
    replay={r['time']:r for r in result['audit']}
    if not saw_cutoff:issues.append('RECORDED_CUTOFF_MISSING')
    fields=('open','high','low','close','ema10','previous_ema10','rsi9','ema3_rsi','wma21_rsi','previous_rsi9','previous_ema3_rsi','previous_wma21_rsi','seeded_bar_count')
    for stamp in expected_times:
        if stamp not in saved:issues.append('RECORDED_DECISION_MISSING:'+stamp);continue
        if stamp not in replay:issues.append('REPLAY_DECISION_MISSING:'+stamp);continue
        if saved[stamp]['strategy_version']!=policy5.VERSION:issues.append('RECORDED_VERSION_MISMATCH:'+stamp)
        frame=saved[stamp]['price_ema_frame'];actual=replay[stamp]['frame']
        if not frame:issues.append('RECORDED_FRAME_MISSING:'+stamp);continue
        for key in fields:
            a,b=frame.get(key),actual.get(key)
            if a is None or b is None or isinstance(a,bool) or isinstance(b,bool):issues.append(stamp+':MISSING_FRAME_FIELD:'+key);continue
            if not math.isfinite(float(a)) or not math.isfinite(float(b)) or abs(float(a)-float(b))>1e-6:issues.append(stamp+':'+key)
    def side(e):
        if e['event_type'] in legacy5.BEARISH_ENTRY_EVENTS|legacy5.BEARISH_EXIT_EVENTS:return 'BEARISH'
        if e['event_type'] in legacy5.BULLISH_ENTRY_EVENTS|legacy5.BULLISH_EXIT_EVENTS:return 'BULLISH'
        issues.append('UNKNOWN_RECORDED_EVENT:'+e['event_type']);return 'UNKNOWN'
    expected_entries=[];expected_exits=[]
    for e in event_map.values():
        if e['exit_reason']:
            expected_exits.append((side(e),e['entry_time'],e['event_time'],round(e['price'],4),round(e['points'],4)))
        else:expected_entries.append((side(e),e['entry_time'],round(e['entry_price'],4)))
    trades=result['trades']+([result['open_trade']] if result['open_trade'] else [])
    actual_entries=[(t['direction'],t['entry_time'],round(t['entry_price'],4)) for t in trades]
    actual_exits=[(t['direction'],t['entry_time'],t['exit_time'],round(t['exit_price'],4),round(t['points'],4)) for t in result['trades']]
    if sorted(expected_entries)!=sorted(actual_entries):issues.append('ENTRY_MISMATCH')
    if sorted(expected_exits)!=sorted(actual_exits):issues.append('EXIT_MISMATCH')
    return dict(status='PASS' if not issues else 'FAIL',issues=issues,checked_boundaries=len(expected_times),
        recorded_entries=sorted(expected_entries),replay_entries=sorted(actual_entries),
        recorded_exits=sorted(expected_exits),replay_exits=sorted(actual_exits))
