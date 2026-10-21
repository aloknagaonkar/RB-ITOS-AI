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

def isolated_three():
    import market_lab
    namespace = types.ModuleType('timing3')
    namespace.__path__ = [str(HERE/'engine3'), str(Path(market_lab.__file__).parent)]
    sys.modules['timing3'] = namespace
    return (importlib.import_module('timing3.hilega_combined_policy_v1'),
            importlib.import_module('timing3.hilega_v2_alignment_replay_v1'))

def run(policy, legacy, warm, raw, day, interval, until):
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
    for bar in aggregate(raw, day, interval, min(until, cutoff)):
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

def parity(result, records, until):
    entries, exits = recorded_events(records, until)
    expected_entries = sorted((e['entry_time'],round(e['entry_price'],4)) for e in entries)
    actual_entries = sorted((e['entry_time'],round(e['entry_price'],4))
        for e in result['trades'] + ([result['open_trade']] if result['open_trade'] else []))
    expected_exits = sorted((e['entry_time'],e['event_time'],round(e['price'],4),round(e['points'],4)) for e in exits)
    actual_exits = sorted((e['entry_time'],e['exit_time'],round(e['exit_price'],4),round(e['points'],4)) for e in result['trades'])
    mismatches = []
    observed=[]
    for row in records:
        p=row.get('payload') or {}
        if row.get('stage') in ('DIRECTIONAL_DECISION','DIRECTIONAL_SESSION_CUTOFF'):
            stamp=p.get('decision_timestamp') or row.get('event_time')
            if stamp:observed.append(datetime.fromisoformat(stamp))
    if not observed or max(observed)<until:
        mismatches.append('RECORDED_AUDIT_DOES_NOT_COVER_REQUESTED_HORIZON')
    if expected_entries != actual_entries: mismatches.append('ENTRY_MISMATCH')
    if expected_exits != actual_exits: mismatches.append('EXIT_MISMATCH')
    # Also compare indicators and OHLC at every recorded decision boundary.
    lookup = {r['time']:r for r in result['audit']}
    for row in records:
        if row.get('stage') != 'DIRECTIONAL_DECISION': continue
        p = row['payload']; at = p.get('decision_timestamp')
        if not at or datetime.fromisoformat(at) > until or at not in lookup: continue
        frame = lookup[at]['frame']; saved = p.get('price_ema_frame')
        if saved:
            for key in ('open','high','low','close','ema10','rsi9','ema3_rsi','wma21_rsi'):
                if saved.get(key) is not None and abs(float(saved[key])-float(frame[key])) > 1e-6:
                    mismatches.append(at+':'+key)
    return dict(status='PASS' if not mismatches else 'FAIL', issues=mismatches,
        recorded_entries=expected_entries, replay_entries=actual_entries,
        recorded_exits=expected_exits, replay_exits=actual_exits)

def verify_sources():
    import market_lab
    expected=json.loads((HERE/'source-hashes.json').read_text())
    for name,digest in expected.items():
        source=Path(market_lab.__file__).parent/(name+'.py')
        if hashlib.sha256(source.read_bytes()).hexdigest()!=digest:
            raise ValueError('SOURCE_CHANGED:'+name)

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input-zip',type=Path,required=True)
    ap.add_argument('--session-input',type=Path,required=True)
    ap.add_argument('--as-of',default='11:55')
    ap.add_argument('--output',type=Path,required=True)
    args = ap.parse_args()
    verify_sources()
    data = json.loads(args.session_input.read_text())
    day = data['session_date']
    until = datetime.fromisoformat(day+'T'+args.as_of+':00+05:30')
    warm, records = read_inputs(args.input_zip)
    five = run(policy5,legacy5,warm,data['candles'],day,5,until)
    proof = parity(five,records,until)
    p3,l3 = isolated_three()
    three = run(p3,l3,warm,data['candles'],day,3,until)
    args.output.mkdir(parents=True,exist_ok=True)
    report = dict(session_date=day,as_of=until.isoformat(),baseline_parity=proof,
        comparison_valid=proof['status']=='PASS',five=five,three=three,
        input_basis='LATER_API_CANDLES',observation_only=True,orders_sent=False)
    (args.output/'report.json').write_text(json.dumps(report,indent=2))
    lines = ['# 5m versus 3m research', '', 'Baseline parity: '+proof['status'],
        'Gross NIFTY points; no option fills/costs. Open marks separate. No live changes.',
        '3m indicators use 3m warmup candles. Same thresholds, not the same indicator time horizon.',
        'If parity FAILS, the 3m result is exploratory and cannot establish improvement over recorded live trades.',
        '', '| Policy | Direction | Setup | Qualified | Entry–exit | Closed points | Open mark points |',
        '|---|---|---|---|---|---:|---:|']
    for label, result in [('5m',five),('3m',three)]:
        for t in result['trades']+([result['open_trade']] if result['open_trade'] else []):
            hm=lambda v: v[11:16] if v else '—'
            span=hm(t['entry_time'])+'–'+(hm(t['exit_time']) if t.get('exit_time') else 'OPEN')
            lines.append(f"| {label} | {t['direction']} | {hm(t['setup'])} | {hm(t['qualified'])} | {span} | {t.get('points',0):+.2f} | {t.get('unrealized_points',0):+.2f} |")
    lines += ['', '| Policy | Closed trades | Closed points | Open mark points |',
        '|---|---:|---:|---:|']
    for label,result in [('5m',five),('3m',three)]:
        lines.append(f"| {label} | {len(result['trades'])} | {result['closed_points']:+.2f} | {(result['open_trade'] or {}).get('unrealized_points',0):+.2f} |")
    lines += ['', '## Entry checks', '',
        '| Policy | Time | Direction | RSI9 | EMA3 RSI | WMA21 | Strength | Gap | Expansion | Status | Reasons |',
        '|---|---|---|---:|---:|---:|---:|---:|---:|---|---|']
    for label,result in [('5m',five),('3m',three)]:
        for boundary in result['audit']:
            for check in boundary['checks']:
                def val(key):
                    v=check.get(key)
                    return f'{v:.3f}' if isinstance(v,(int,float)) else '—'
                lines.append('| '+' | '.join([label,boundary['time'][11:16],check['direction'],
                    val('current_rsi9'),val('current_ema3'),val('current_wma21'),
                    val('directional_wma_strength'),val('current_gap'),val('gap_delta'),
                    check.get('status','—'),', '.join(check.get('reasons',[])) or 'PASS'])+' |')
    (args.output/'comparison.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines))
    print('REPORT:',args.output/'report.json')
    print('PARITY ISSUES:',json.dumps(proof['issues']))

if __name__ == '__main__': main()
