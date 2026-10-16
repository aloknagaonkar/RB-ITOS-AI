"""Read-only VWAP signal-filter research. No orders, control changes, or replay claims."""
import argparse
import csv
import json
import math
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote
from zoneinfo import ZoneInfo

from hilega_vwap_signal_review.collect import dt, vwap_at
from market_lab.hilega_directional_coordinator_v1 import (
    BULLISH_ENTRY_EVENTS, BEARISH_ENTRY_EVENTS, BULLISH_EXIT_EVENTS, BEARISH_EXIT_EVENTS)

IST = ZoneInfo('Asia/Kolkata')
STRATEGY = 'HILEGA_V2_ALIGNMENT_DUAL_EXIT'
ENTRY = BULLISH_ENTRY_EVENTS | BEARISH_ENTRY_EVENTS
EXIT = BULLISH_EXIT_EVENTS | BEARISH_EXIT_EVENTS


def side(event):
    return 'BEARISH' if event in BEARISH_ENTRY_EVENTS | BEARISH_EXIT_EVENTS else 'BULLISH'


def number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError('NONFINITE_PRICE_OR_POINTS')
    return float(value)


def read_audit(path):
    rows=[]
    with path.open() as stream:
        for line in stream:
            if not line.endswith('\n'):continue
            r=json.loads(line);p=r.get('payload') or {}
            if p.get('strategy_id')!=STRATEGY:continue
            if r.get('status') not in {'PROCESSED','RECOVERED'}:continue
            if r.get('stage') not in {'DIRECTIONAL_DECISION','DIRECTIONAL_SESSION_CUTOFF','DIRECTIONAL_MANUAL_EXIT_RESET'}:continue
            at=p.get('decision_timestamp') or p.get('cutoff_timestamp') or p.get('completed_at') or r.get('event_time')
            if not at:continue
            rows.append(dict(record=r,payload=p,at=dt(at)))
    return rows


def audit_trades(records, day, version):
    records=[r for r in records if r['at'].date().isoformat()==day]
    decisions=[r for r in records if r['record']['stage']!='DIRECTIONAL_MANUAL_EXIT_RESET']
    if not decisions:raise ValueError('NO_AUDIT_SESSION')
    if any(r['payload'].get('strategy_version')!=version for r in decisions):
        raise ValueError('AUDIT_STRATEGY_VERSION_MISMATCH')
    groups={}
    for row in records:
        key=(row['at'],row['record']['stage']);prior=groups.get(key)
        rank=2 if row['record'].get('status')=='PROCESSED' else 1
        if prior and rank==prior[0]==2 and row['payload'].get('event_details')!=prior[1]['payload'].get('event_details'):
            raise ValueError('CONFLICTING_PROCESSED_DECISIONS')
        if prior is None or rank>prior[0]:groups[key]=(rank,row)
    active=None;trades=[];seen=set();cutoff=False
    ordered=sorted((item[1] for item in groups.values()),key=lambda r:(r['at'],int(r['record'].get('sequence') or 0)))
    for row in ordered:
        p=row['payload'];at=row['at'].isoformat()
        if row['record']['stage']=='DIRECTIONAL_MANUAL_EXIT_RESET':
            if active:
                active.update(exit_time=at,exit_price=None,points=None,exit_reason='MANUAL_RESET_UNPRICED',coverage_issue='NO_VERIFIED_NIFTY_EXIT_PRICE')
                trades.append(active);active=None
            continue
        cutoff=cutoff or row['record']['stage']=='DIRECTIONAL_SESSION_CUTOFF' or row['at'].time().replace(tzinfo=None)>=datetime.strptime('14:55','%H:%M').time()
        events=p.get('event_details') or []
        detailed={e.get('event_type') for e in events}
        if (set(p.get('accepted_events') or []) & (ENTRY|EXIT))-detailed:
            raise ValueError('MISSING_ACCEPTED_EVENT_DETAILS')
        for event in sorted(events,key=lambda e:0 if e.get('event_type') in EXIT else 1):
            name=event.get('event_type')
            if name not in ENTRY|EXIT:continue
            entry_time=dt(event['entry_time']).isoformat() if event.get('entry_time') else at
            identity=(name,entry_time,at)
            if identity in seen:continue
            seen.add(identity)
            if name in ENTRY:
                if active:raise ValueError('OVERLAPPING_BASELINE_ENTRIES')
                if entry_time!=at:raise ValueError('ENTRY_TIME_DIFFERS_FROM_CONFIRMED_DECISION')
                active=dict(direction=side(name),entry_time=at,entry_price=number(event.get('entry_price') if event.get('entry_price') is not None else event['price']),setup_time=None,entry_event=name)
            else:
                if not active or active['entry_time']!=entry_time or active['direction']!=side(name):
                    raise ValueError('UNMATCHED_BASELINE_EXIT')
                price=number(event['price']);points=(price-active['entry_price'])*(1 if active['direction']=='BULLISH' else -1)
                reference=number(event['entry_price']) if event.get('entry_price') is not None else active['entry_price']
                reference_points=(price-reference)*(1 if active['direction']=='BULLISH' else -1)
                if event.get('points') is not None and abs(number(event['points'])-reference_points)>1e-5:
                    raise ValueError('EXIT_EVENT_INTERNAL_POINTS_MISMATCH')
                active.update(points_basis='FROZEN_CONFIRMED_ENTRY_TO_EXIT',
                              recorded_exit_points=event.get('points'),
                              exit_event_entry_reference=reference,
                              entry_reference_delta=reference-active['entry_price'],
                              entry_reference_changed=abs(reference-active['entry_price'])>1e-5)
                active.update(exit_time=at,exit_price=price,points=points,exit_reason=event.get('exit_reason') or name)
                trades.append(active);active=None
    if active:raise ValueError('OPEN_OR_MISSING_EXIT_BASELINE_TRADE')
    if not cutoff:raise ValueError('SESSION_END_EVIDENCE_MISSING')
    return trades


def replay_trades(path, day, version):
    p=json.loads(path.read_text())
    if p.get('strategy_version')!=version:raise ValueError('REPLAY_STRATEGY_VERSION_MISMATCH')
    if p.get('session_date')!=day or not isinstance(p.get('trades'),list):raise ValueError('INVALID_REPLAY_SESSION')
    trades=[];previous_exit=None
    for raw in sorted(p['trades'],key=lambda r:dt(r['entry_time'])):
        entry=dt(raw['entry_time']);exit_at=dt(raw['exit_time']);direction=raw['direction']
        if entry.date().isoformat()!=day or exit_at.date()!=entry.date() or exit_at<entry or direction not in {'BULLISH','BEARISH'}:
            raise ValueError('INVALID_REPLAY_TRADE')
        if previous_exit and entry<previous_exit:raise ValueError('OVERLAPPING_REPLAY_TRADES')
        previous_exit=exit_at
        price=number(raw['entry_price']);exit_price=number(raw['exit_price']);points=(exit_price-price)*(1 if direction=='BULLISH' else -1)
        if raw.get('points') is not None and abs(number(raw['points'])-points)>1e-5:raise ValueError('REPLAY_POINTS_MISMATCH')
        trades.append(dict(direction=direction,entry_time=entry.isoformat(),exit_time=exit_at.isoformat(),entry_price=price,exit_price=exit_price,points=points,setup_time=raw.get('signal_time'),exit_reason=raw.get('exit_reason')))
    return trades


def cached_futures(day, output):
    options=[
        (output/f'{day}-contract.json',output/f'{day}-futures.json'),
        (Path('data/live-observation/hilega-vwap-signal-v1')/f'{day}-futures-contract.json',Path('data/live-observation/hilega-vwap-signal-v1')/f'{day}-futures-ohlcv.json'),
        (Path('data/research/hilega-vwap-oct13-14')/f'{day}-futures-contract.json',Path('data/research/hilega-vwap-oct13-14')/f'{day}-futures-ohlcv.json'),
        (Path('data/research/hilega-vwap-previous5-replay')/f'{day}-contract.json',Path('data/research/hilega-vwap-previous5-replay')/f'{day}-futures.json')]
    for manifest,candles in options:
        if manifest.exists() and candles.exists():
            contract=json.loads(manifest.read_text())
            if contract.get('underlying_key')!='NSE_INDEX|Nifty 50' or not contract.get('instrument_key') or str(contract.get('expiry',''))<day:
                raise ValueError('INVALID_CACHED_FUTURES_MANIFEST')
            return contract,json.loads(candles.read_text())['data']['candles'],str(candles)
    return None


def fetch_futures(day, output):
    from dataclasses import asdict
    from dotenv import load_dotenv
    from market_lab.upstox_live_futures_v1 import UpstoxLiveFuturesGatewayV1
    load_dotenv('.env');token=os.getenv('UPSTOX_ACCESS_TOKEN')
    if not token:raise ValueError('UPSTOX_ACCESS_TOKEN_MISSING')
    session=date.fromisoformat(day);today=datetime.now(IST).date()
    if (session.year,session.month)!=(today.year,today.month):raise ValueError('HISTORICAL_FUTURES_MANIFEST_REQUIRED')
    gateway=UpstoxLiveFuturesGatewayV1(token)
    try:
        instrument=gateway.resolve_nifty_front_future(today=session);key=quote(instrument.instrument_key,safe='')
        endpoint=f'/v3/historical-candle/intraday/{key}/minutes/5' if session==today else f'/v3/historical-candle/{key}/minutes/5/{day}/{day}'
        body=gateway._get(endpoint)
        manifest=asdict(instrument)
        (output/f'{day}-contract.json').write_text(json.dumps(manifest,default=str,indent=2))
        path=output/f'{day}-futures.json';path.write_text(json.dumps(body,indent=2))
        return manifest,body['data']['candles'],str(path)
    finally:gateway.close()


def evaluate(trade, candles):
    value=dict(trade,alignment=None,alignment_and_slope=None)
    at=dt(trade['entry_time'])
    try:
        current=vwap_at(candles,at)
        aligned=current['distance_points']>0 if trade['direction']=='BULLISH' else current['distance_points']<0
        value.update(vwap=current['vwap'],futures_close=current['futures_close'],vwap_distance=current['distance_points'],candle_available_at=current['candle_available_at'],alignment=aligned,alignment_and_slope=False if not aligned else None)
    except (ValueError,TypeError,KeyError,IndexError) as exc:
        value['vwap_issue']=str(exc) if isinstance(exc,ValueError) else type(exc).__name__;return value
    try:
        prior=vwap_at(candles,dt(current['candle_available_at'])-timedelta(minutes=5))
        slope=current['vwap']-prior['vwap']
        value.update(previous_vwap=prior['vwap'],vwap_slope_5m=slope,
                     alignment_and_slope=aligned and (slope>0 if trade['direction']=='BULLISH' else slope<0))
    except (ValueError,TypeError,KeyError,IndexError):
        value['slope_issue']='PREVIOUS_COMPLETED_VWAP_UNAVAILABLE'
    return value


def stats(rows):
    values=[r['points'] for r in rows if r.get('points') is not None]
    profit=sum(v for v in values if v>0);loss=-sum(v for v in values if v<0)
    cumulative=peak=drawdown=0.
    for v in values:
        cumulative+=v;peak=max(peak,cumulative);drawdown=max(drawdown,peak-cumulative)
    return dict(priced_trades=len(values),unpriced_trades=len(rows)-len(values),winners=sum(v>0 for v in values),losers=sum(v<0 for v in values),net_nifty_points=round(sum(values),4),gross_profit_points=round(profit,4),gross_loss_points=round(loss,4),profit_factor=profit/loss if loss else None,max_closed_trade_drawdown_points=round(drawdown,4))


def day_context(day, candles):
    """End-of-day description only. Never used in an entry filter."""
    context=dict(usage='POST_SESSION_DESCRIPTION_NOT_AN_ENTRY_FILTER')
    try:
        end=dt(day+'T15:30:00+05:30')
        vwap_at(candles,end)  # Require the entire session path before describing it.
        path=sorted((row for row in candles if dt(row[0]).date().isoformat()==day and
                     day+'T09:15:00+05:30'<=dt(row[0]).isoformat()<day+'T15:30:00+05:30'),key=lambda row:dt(row[0]))
        closes=[number(row[4]) for row in path]
        variation=sum(abs(b-a) for a,b in zip(closes,closes[1:]))
        movement=closes[-1]-closes[0]
        positions=[]
        for row in path:
            value=vwap_at(candles,dt(row[0])+timedelta(minutes=5))
            positions.append(1 if value['distance_points']>0 else -1 if value['distance_points']<0 else 0)
        context.update(status='AVAILABLE',futures_first_to_last_close_points=round(movement,4),
                       directional_efficiency=abs(movement)/variation if variation else 0.,
                       closes_above_vwap=sum(v>0 for v in positions),closes_below_vwap=sum(v<0 for v in positions),
                       vwap_side_changes=sum(a!=b for a,b in zip(positions,positions[1:]) if a and b),completed_candles=len(path))
    except (ValueError,KeyError,TypeError,IndexError) as exc:
        context.update(status='UNAVAILABLE',reason=str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
    return context


def comparison(rows, rule):
    comparable=[r for r in rows if r.get(rule) is not None and r.get('points') is not None]
    passed=[r for r in comparable if r[rule]];blocked=[r for r in comparable if not r[rule]]
    return dict(rule=rule,baseline_same_coverage=stats(comparable),passed=stats(passed),blocked=stats(blocked),
                blocked_losing_trades=sum(r['points']<0 for r in blocked),avoided_loss_points=round(-sum(r['points'] for r in blocked if r['points']<0),4),
                blocked_winning_trades=sum(r['points']>0 for r in blocked),forgone_profit_points=round(sum(r['points'] for r in blocked if r['points']>0),4),
                excluded_unknown_rule=sum(r.get(rule) is None for r in rows),
                excluded_unpriced=sum(r.get('points') is None for r in rows),
                improvement_points=round(stats(passed)['net_nifty_points']-stats(comparable)['net_nifty_points'],4))


def markdown(report):
    lines=['# HILEGA VWAP last-five-session comparison','',
           'Status: '+report['status']+'; strategy '+report['strategy_version']+'.','',
           report['warning'],'',
           '| Rule | Comparable baseline points | Passed points | Losing trades blocked | Loss points avoided | Winners blocked | Profit points forgone | Net change | Unknown rule |',
           '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for item in report['comparisons']:
        lines.append(f"| {item['rule']} | {item['baseline_same_coverage']['net_nifty_points']:.2f} | {item['passed']['net_nifty_points']:.2f} | {item['blocked_losing_trades']} | {item['avoided_loss_points']:.2f} | {item['blocked_winning_trades']} | {item['forgone_profit_points']:.2f} | {item['improvement_points']:.2f} | {item['excluded_unknown_rule']} |")
    lines+=['','## By session','',
            '| Date | Baseline points | Alignment passed points | Alignment + slope passed points | End-of-day directional efficiency | Baseline source |',
            '|---|---:|---:|---:|---:|---|']
    for day in report['daily']:
        efficiency=day['trend_context'].get('directional_efficiency')
        label=f'{efficiency:.3f}' if efficiency is not None else 'Unavailable'
        lines.append(f"| {day['session_date']} | {day['baseline']['net_nifty_points']:.2f} | {day['rules'][0]['passed']['net_nifty_points']:.2f} | {day['rules'][1]['passed']['net_nifty_points']:.2f} | {label} | {day['baseline_source']} |")
    lines+=['','Directional efficiency is an end-of-day description, never an entry filter. Daily rule totals may have different coverage; use the matched-coverage comparison above.','',
            '## Individual trades','',
            '| Date | Direction | Entry | Exit | NIFTY points | VWAP alignment | Alignment + slope |',
            '|---|---|---|---|---:|---|---|']
    def verdict(value):return 'PASS' if value is True else 'BLOCK' if value is False else 'UNAVAILABLE'
    for row in report['trades']:
        points=f"{row['points']:.2f}" if row.get('points') is not None else 'Unpriced'
        lines.append(f"| {row['session_date']} | {row['direction']} | {dt(row['entry_time']).strftime('%H:%M')} | {dt(row['exit_time']).strftime('%H:%M')} | {points} | {verdict(row.get('alignment'))} | {verdict(row.get('alignment_and_slope'))} |")
    lines+=['','## Coverage','']
    lines.extend('- '+json.dumps(value) for value in report['coverage'])
    changed=[row for row in report['trades'] if row.get('entry_reference_changed')]
    if changed:
        lines+=['','## Entry-reference discrepancies','',
                'Comparison points use the original confirmed entry and recorded exit. Recorded strategy points may use a different entry reference after restoration. Neither source value is overwritten.','',
                '| Date | Entry | Original entry | Exit-event entry reference | Frozen-entry points | Recorded strategy points |',
                '|---|---|---:|---:|---:|---:|']
        for row in changed:
            lines.append(f"| {row['session_date']} | {dt(row['entry_time']).strftime('%H:%M')} | {row['entry_price']:.2f} | {row['exit_event_entry_reference']:.2f} | {row['points']:.2f} | {row.get('recorded_exit_points')} |")
    return '\n'.join(lines)+'\n'


def run(args):
    output=args.output;output.mkdir(parents=True,exist_ok=True)
    records=read_audit(args.audit)
    days={r['at'].date().isoformat() for r in records}
    days.update(p.stem for p in args.replay_root.glob('????-??-??.json'))
    days=sorted(day for day in days if day<=args.end_date)[-5:]
    if len(days)!=5:raise ValueError('FIVE_RECORDED_SESSIONS_REQUIRED')
    all_trades=[];coverage=[];daily=[]
    for day in days:
        entry=dict(session_date=day,status='UNAVAILABLE',issues=[])
        try:
            try:
                trades=audit_trades(records,day,args.expected_version);origin='VERSION_VERIFIED_AUDIT'
            except ValueError as exc:
                entry['issues'].append(str(exc));path=args.replay_root/(day+'.json')
                if not path.exists():raise ValueError('VERSION_MATCHED_BASELINE_REQUIRED')
                trades=replay_trades(path,day,args.expected_version);origin='VERSION_VERIFIED_RESEARCH_REPLAY'
            futures=cached_futures(day,output)
            if futures is None:
                if not args.fetch_missing:raise ValueError('FUTURES_CACHE_MISSING_USE_FETCH_MISSING')
                futures=fetch_futures(day,output)
            contract,candles,cache_path=futures
            rows=[dict(evaluate(trade,candles),session_date=day,baseline_source=origin,strategy_version=args.expected_version,instrument_key=contract['instrument_key'],futures_cache=cache_path) for trade in trades]
            all_trades.extend(rows)
            complete=all(r.get('points') is not None and r.get('alignment_and_slope') is not None for r in rows)
            entry.update(status='AVAILABLE' if complete else 'INCOMPLETE',baseline_source=origin,trades=len(rows),priced=sum(r.get('points') is not None for r in rows),vwap_available=sum(r.get('alignment') is not None for r in rows),slope_available=sum(r.get('alignment_and_slope') is not None for r in rows))
            daily.append(dict(session_date=day,baseline_source=origin,trend_context=day_context(day,candles),baseline=stats(rows),rules=[comparison(rows,key) for key in ('alignment','alignment_and_slope')]))
        except Exception as exc:
            entry['issues'].append(str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
        coverage.append(entry)
    all_trades.sort(key=lambda r:dt(r['entry_time']))
    report=dict(status='COMPLETE' if all(r['status']=='AVAILABLE' for r in coverage) else 'INCOMPLETE',session_dates=days,strategy_version=args.expected_version,observation_only=True,entry_filter_enabled=False,
                method='FIXED_BASELINE_TRADE_FILTER_COMPARISON_NOT_STATEFUL_STRATEGY_REPLAY',
                warning='Gross NIFTY points, not option P&L. Original confirmed entry prices and exit times/prices retained. Restored entry-reference discrepancies are disclosed separately. Filtering may change future strategy state; this report does not model that effect. Five sessions cannot establish a robust edge. Reconstructed futures five-minute typical-price VWAP, not index VWAP.',
                rules=dict(alignment='Bullish: completed futures close > VWAP; bearish: close < VWAP. At VWAP fails.',alignment_and_slope='Alignment plus cumulative session VWAP rising over the previous completed five-minute boundary for bullish, falling for bearish. Flat slope fails; unavailable slope is unknown, not blocked.'),
                coverage=coverage,baseline=stats(all_trades),comparisons=[comparison(all_trades,key) for key in ('alignment','alignment_and_slope')],daily=daily,trades=all_trades)
    path=output/'report.json';path.write_text(json.dumps(report,indent=2)+'\n')
    fields=['session_date','direction','setup_time','entry_time','exit_time','entry_price','exit_price','points','points_basis','recorded_exit_points','exit_event_entry_reference','entry_reference_delta','entry_reference_changed','exit_reason','vwap','futures_close','vwap_distance','candle_available_at','vwap_slope_5m','alignment','alignment_and_slope','baseline_source','strategy_version','vwap_issue','slope_issue','coverage_issue']
    with (output/'trades.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(all_trades)
    summary=markdown(report);(output/'summary.md').write_text(summary)
    print(summary)
    print('REPORT:',path)


class ResearchChecks(unittest.TestCase):
    def test_no_future_candle_in_filter(self):
        candles=[['2026-10-15T09:15:00+05:30',100,102,98,100,10],['2026-10-15T09:20:00+05:30',100,105,100,104,20],['2026-10-15T09:25:00+05:30',100,1000,100,999,10000]]
        result=evaluate(dict(direction='BULLISH',entry_time='2026-10-15T09:26:00+05:30'),candles)
        self.assertTrue(result['alignment_and_slope']);self.assertEqual(result['futures_close'],104)
    def test_first_bar_slope_unknown(self):
        result=evaluate(dict(direction='BULLISH',entry_time='2026-10-15T09:21:00+05:30'),[['2026-10-15T09:15:00+05:30',100,102,98,101,10]])
        self.assertIsNone(result['alignment_and_slope'])
    def test_blocked_winners_are_counted(self):
        value=comparison([dict(points=-10,alignment=False),dict(points=6,alignment=False),dict(points=20,alignment=True),dict(points=-100,alignment=None)],'alignment')
        self.assertEqual(value['improvement_points'],4);self.assertEqual(value['blocked_winning_trades'],1);self.assertEqual(value['excluded_unknown_rule'],1)
    def test_manual_reset_does_not_invent_exit(self):
        def r(at,stage,payload):return dict(at=dt(at),record=dict(stage=stage,status='PROCESSED'),payload=dict(strategy_version='v',**payload))
        at='2026-10-15T09:25:00+05:30'
        rows=[r(at,'DIRECTIONAL_DECISION',dict(event_details=[dict(event_type=sorted(BULLISH_ENTRY_EVENTS)[0],entry_time=at,entry_price=100)])),r('2026-10-15T10:00:00+05:30','DIRECTIONAL_MANUAL_EXIT_RESET',{}),r('2026-10-15T14:55:00+05:30','DIRECTIONAL_SESSION_CUTOFF',dict(event_details=[]))]
        self.assertIsNone(audit_trades(rows,'2026-10-15','v')[0]['points'])
    def test_version_mix_rejected(self):
        with self.assertRaisesRegex(ValueError,'VERSION_MISMATCH'):
            audit_trades([dict(at=dt('2026-10-15T14:55:00+05:30'),record=dict(stage='DIRECTIONAL_DECISION'),payload=dict(strategy_version='old'))],'2026-10-15','new')
    def test_restored_entry_reference_is_disclosed_without_dropping_session(self):
        at='2026-10-14T09:27:00+05:30'
        def r(ts,stage,events):
            return dict(at=dt(ts),record=dict(stage=stage,status='PROCESSED'),payload=dict(strategy_version='v',event_details=events))
        records=[r(at,'DIRECTIONAL_DECISION',[dict(event_type='ENTRY_BEARISH_ROUTE_B_STRUCTURAL',entry_time=at,entry_price=22689.2)]),
                 r('2026-10-14T10:40:00+05:30','DIRECTIONAL_DECISION',[dict(event_type='STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21',entry_time=at,entry_price=22688.45,price=22717.,points=-28.55)]),
                 r('2026-10-14T14:55:00+05:30','DIRECTIONAL_SESSION_CUTOFF',[])]
        trade=audit_trades(records,'2026-10-14','v')[0]
        self.assertAlmostEqual(trade['points'],-27.8)
        self.assertAlmostEqual(trade['recorded_exit_points'],-28.55)
        self.assertTrue(trade['entry_reference_changed'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit',type=Path,default=Path('data/live-observation/hilega-directional-v1/step-audit.jsonl'))
    parser.add_argument('--replay-root',type=Path,default=Path('data/research/hilega-last10-atm5-20261013-gross/replays'))
    parser.add_argument('--expected-version',default='five-minute-setup-1.2.0-pending-switch')
    parser.add_argument('--end-date',default='2026-10-15')
    parser.add_argument('--output',type=Path,default=Path('data/research/hilega-vwap-last5-comparison-20261015'))
    parser.add_argument('--fetch-missing',action='store_true',help='GET-only futures data acquisition into this research folder')
    parser.add_argument('--test',action='store_true')
    args=parser.parse_args()
    if args.test:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ResearchChecks))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    date.fromisoformat(args.end_date)
    run(args)




# Appended to the frozen five-session evaluator to make a standalone runner.
import calendar
import hashlib
import time as research_time
import fcntl
import httpx

UNDERLYING='NSE_INDEX|Nifty 50'


def month_start(end, months):
    index=end.year*12+end.month-1-months
    year,month=divmod(index,12);month+=1
    return date(year,month,min(end.day,calendar.monthrange(year,month)[1]))+timedelta(days=1)


def save_json(path, payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    with temp.open('w') as stream:
        json.dump(payload,stream,indent=2,default=str);stream.flush();os.fsync(stream.fileno())
    os.replace(temp,path)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()


class ResearchData:
    """Allowlisted GET-only provider client with immutable, checked raw caches."""
    def __init__(self, root, fetch):
        from dotenv import dotenv_values
        self.root=root;self.fetch=fetch;self.last_request=0.
        token=os.getenv('UPSTOX_ACCESS_TOKEN') or dotenv_values('.env').get('UPSTOX_ACCESS_TOKEN')
        self.client=httpx.Client(base_url='https://api.upstox.com',headers={'Authorization':f'Bearer {token or ""}'},timeout=30)
        self.has_token=bool(token)
    def close(self):self.client.close()
    def get(self, path, params=None):
        if not path.startswith(('/v3/historical-candle/','/v2/expired-instruments/expiries','/v2/expired-instruments/future/contract','/v2/expired-instruments/historical-candle/','/v2/instruments/search')):
            raise ValueError('RESEARCH_GET_ROUTE_NOT_ALLOWED')
        request=dict(path=path,params=params or {});dest=self.root/(fingerprint(request)+'.json')
        if dest.exists():
            row=json.loads(dest.read_text())
            if row['request']!=request or fingerprint(row['body'])!=row['body_sha256']:
                raise ValueError('RAW_PROVIDER_CACHE_IDENTITY_OR_HASH_MISMATCH')
            return row['body']
        if not self.fetch:raise ValueError('RAW_PROVIDER_CACHE_MISSING_USE_FETCH_MISSING')
        if not self.has_token:raise ValueError('UPSTOX_ACCESS_TOKEN_MISSING')
        for attempt in range(3):
            research_time.sleep(max(0.,.5-(research_time.monotonic()-self.last_request)))
            self.last_request=research_time.monotonic()
            try:response=self.client.get(path,params=params or {})
            except httpx.RequestError:
                if attempt<2:research_time.sleep(2**attempt);continue
                raise ValueError('PROVIDER_NETWORK_REQUEST_FAILED') from None
            if response.status_code==429 or response.status_code>=500:
                if attempt<2:research_time.sleep(2**attempt);continue
            try:body=response.json()
            except ValueError:raise ValueError('UPSTOX_NON_JSON_RESPONSE') from None
            if not response.is_success or body.get('status')!='success':
                codes=','.join(str(e.get('errorCode') or e.get('error_code') or '') for e in body.get('errors',[]))
                raise ValueError(f'UPSTOX_HTTP_{response.status_code}:{codes}')
            save_json(dest,dict(request=request,body=body,body_sha256=fingerprint(body),received_at=datetime.now(IST).isoformat()))
            return body
        raise ValueError('PROVIDER_REQUEST_FAILED')


def group_minutes(raw):
    days={};seen={}
    for row in raw:
        at=dt(row[0]);day=at.date().isoformat()
        if not '09:15'<=at.strftime('%H:%M')<'15:30':continue
        if at.second or at.microsecond:raise ValueError('NON_MINUTE_UNDERLYING_TIMESTAMP')
        values=[number(v) for v in row[1:5]]
        if min(values)<=0 or values[1]<max(values[0],values[2],values[3]) or values[2]>min(values[0],values[1],values[3]):
            raise ValueError('INVALID_UNDERLYING_OHLC')
        record=dict(timestamp=at.isoformat(),open=values[0],high=values[1],low=values[2],close=values[3],volume=row[5] if len(row)>5 else None)
        if at in seen:
            if seen[at]!=record:raise ValueError('CONFLICTING_UNDERLYING_MINUTES')
            continue
        seen[at]=record;days.setdefault(day,[]).append(record)
    return {day:sorted(rows,key=lambda r:dt(r['timestamp'])) for day,rows in days.items()}


def underlying_data(gateway, start, end):
    encoded=quote(UNDERLYING,safe='')
    calendar_body=gateway.get(f'/v3/historical-candle/{encoded}/days/1/{end}/{start}')
    sessions=sorted({dt(row[0]).date().isoformat() for row in calendar_body['data']['candles'] if start<=dt(row[0]).date()<=end})
    if not sessions:raise ValueError('PROVIDER_SESSION_CALENDAR_EMPTY')
    raw=[];cursor=start
    while cursor<=end:
        first=cursor
        last=min(end,cursor+timedelta(days=27))
        body=gateway.get(f'/v3/historical-candle/{encoded}/minutes/1/{last}/{cursor}')
        raw.extend(body['data']['candles']);cursor=last+timedelta(days=1)
        print(f'Underlying cache {first} through {last}',flush=True)
    return sessions,group_minutes(raw)


def future_catalog(gateway, start, end):
    """Provider-returned identities only; never manufacture an expired key."""
    today=datetime.now(IST).date();result=[];issues=[]
    try:
        expiries=gateway.get('/v2/expired-instruments/expiries',{'instrument_key':UNDERLYING})['data']
        if not isinstance(expiries,list):raise ValueError('INVALID_EXPIRY_SCHEDULE')
        for expiry in sorted(set(str(value) for value in expiries)):
            if not start<=date.fromisoformat(expiry)<=min(today,end+timedelta(days=35)):continue
            try:
                body=gateway.get('/v2/expired-instruments/future/contract',{'instrument_key':UNDERLYING,'expiry_date':expiry})
                for raw in body['data']:
                    if raw.get('underlying_key')==UNDERLYING and raw.get('instrument_type')=='FUT' and raw.get('expiry')==expiry:
                        result.append(dict(raw,contract_endpoint='EXPIRED'))
            except Exception as exc:
                issues.append(expiry+':'+(str(exc) if isinstance(exc,ValueError) else type(exc).__name__))
    except Exception as exc:
        issues.append(str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
    # Current search is used only for the current month, never to fill older months.
    try:
        for page in range(1,6):
            body=gateway.get('/v2/instruments/search',dict(query='NIFTY',exchanges='NSE',segments='FO',instrument_types='FUT',expiry='current_month',page_number=page,records=30))
            rows=body.get('data') or []
            if not isinstance(rows,list):raise ValueError('INVALID_ACTIVE_FUTURES_CATALOG')
            for raw in rows:
                if raw.get('underlying_key')==UNDERLYING and raw.get('instrument_type')=='FUT':
                    result.append(dict(raw,contract_endpoint='ACTIVE'))
            if len(rows)<30:break
    except Exception as exc:
        issues.append(str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
    unique={row['instrument_key']:row for row in result}
    return list(unique.values()),issues


def resolve_front(catalog, day):
    # A current-month search cannot verify an earlier month's nearest expiry.
    month=day[:7]
    candidates=[r for r in catalog if str(r.get('expiry',''))>=day and str(r.get('expiry',''))[:7]==month]
    if not candidates:
        # After the last verified expiry of a month, the next monthly contract is front.
        expired_this_month=[r for r in catalog if str(r.get('expiry',''))[:7]==month and str(r['expiry'])<day]
        if not expired_this_month:raise ValueError('SESSION_MONTH_FUTURES_MANIFEST_MISSING')
        candidates=[r for r in catalog if str(r.get('expiry',''))>=day]
    if not candidates:raise ValueError('FRONT_FUTURES_CONTRACT_MISSING')
    expiry=min(str(r['expiry']) for r in candidates)
    matches=[r for r in candidates if str(r['expiry'])==expiry]
    if len(matches)!=1:raise ValueError('AMBIGUOUS_FRONT_FUTURES_CONTRACT')
    return matches[0]


def aggregate_futures(raw, day):
    """Build five-minute bars only from all five exact provider minute rows."""
    minutes={}
    for row in raw:
        at=dt(row[0])
        if at.date().isoformat()!=day or not '09:15'<=at.strftime('%H:%M')<'15:30':continue
        if at in minutes:raise ValueError('DUPLICATE_FUTURES_MINUTE')
        if at.second or at.microsecond:raise ValueError('NON_MINUTE_FUTURES_TIMESTAMP')
        o,h,l,c,v=map(number,row[1:6])
        if min(o,h,l,c)<=0 or v<0 or h<max(o,l,c) or l>min(o,h,c):raise ValueError('INVALID_FUTURES_MINUTE')
        minutes[at]=(o,h,l,c,v)
    result=[];start=dt(day+'T09:15:00+05:30')
    for index in range(75):
        at=start+timedelta(minutes=index*5);keys=[at+timedelta(minutes=n) for n in range(5)]
        if not all(key in minutes for key in keys):continue
        rows=[minutes[key] for key in keys]
        result.append([at.isoformat(),rows[0][0],max(r[1] for r in rows),min(r[2] for r in rows),rows[-1][3],sum(r[4] for r in rows)])
    return result


def fetch_session_future(gateway, contract, day):
    key=quote(contract['instrument_key'],safe='')
    if contract['contract_endpoint']=='EXPIRED':
        path=f'/v2/expired-instruments/historical-candle/{key}/1minute/{day}/{day}'
    else:path=f'/v3/historical-candle/{key}/minutes/1/{day}/{day}'
    return aggregate_futures(gateway.get(path)['data']['candles'],day)


def research_replays(sessions, grouped, start, end, output, version, coverage_only):
    # This flag belongs solely to this standalone research process.
    os.environ['HILEGA_PENDING_OPPOSITE_SWITCH_ENABLED']='1'
    from market_lab import hilega_v2_alignment_replay_v1 as engine
    if engine.RULES['version']!=version:raise ValueError('RESEARCH_ENGINE_VERSION_MISMATCH')
    import market_lab.hilega_milega_strategy_v1 as bullish
    import market_lab.hilega_milega_bearish_strategy_v1 as bearish
    import market_lab.hilega_opening_reference_v1 as opening
    hashes={Path(module.__file__).name:hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() for module in (engine,bullish,bearish,opening)}
    results={};issues={}
    for day in (d for d in sessions if start<=date.fromisoformat(d)<=end and d in TARGET_DAYS):
        try:
            raw=grouped.get(day,[])
            warm=[(d,grouped[d]) for d in sessions if d<day and grouped.get(d)][-30:]
            if len(warm)<20:raise ValueError('TWENTY_PRIOR_WARMUP_SESSIONS_REQUIRED')
            key=fingerprint(dict(raw=raw,warm=warm,source_hashes=hashes,version=version))
            path=output/'replays'/(day+'.json')
            if path.exists():
                previous=json.loads(path.read_text())
                if previous.get('manifest',{}).get('monthly_research_fingerprint')==key:
                    results[day]=replay_trades(path,day,version);continue
            if coverage_only:
                issues[day]='BASELINE_REPLAY_NOT_PREPARED';continue
            result=engine.replay(day,raw,warm,dict(monthly_research_fingerprint=key,source_hashes=hashes,source='UNIFORM_CURRENT_STRATEGY_RECONSTRUCTION',chart_parity_verified=False,manual_interventions_replayed=False,warmup_sessions=len(warm)))
            if result.get('strategy_version')!=version:raise ValueError('REPLAY_OUTPUT_VERSION_MISMATCH')
            save_json(path,result);results[day]=replay_trades(path,day,version)
            print(f'Replay {day}: {len(results[day])} trades',flush=True)
        except Exception as exc:
            issues[day]=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
    return results,issues,hashes


def period_report(rows, coverage, start, end, version, period):
    selected=[r for r in rows if start.isoformat()<=r['session_date']<=end.isoformat()]
    selected.sort(key=lambda r:dt(r['entry_time']))
    checks=[c for c in coverage if start.isoformat()<=c['session_date']<=end.isoformat()]
    daily=[]
    for check in checks:
        day=check['session_date'];trades=[r for r in selected if r['session_date']==day]
        daily.append(dict(session_date=day,baseline_source='UNIFORM_VERSION_VERIFIED_RESEARCH_REPLAY',trend_context=check.get('trend_context',{}),baseline=stats(trades),rules=[comparison(trades,k) for k in ('alignment','alignment_and_slope')]))
    aligned_complete=bool(checks) and all(c.get('alignment_coverage')=='COMPLETE' for c in checks)
    return dict(model='HILEGA_VWAP_MONTHLY_RESEARCH_V1',status='COMPLETE' if aligned_complete else 'INCOMPLETE',period=period,start_date=str(start),end_date=str(end),session_dates=[c['session_date'] for c in checks],strategy_version=version,observation_only=True,entry_filter_enabled=False,
                method='FIXED_BASELINE_TRADE_FILTER_COMPARISON_NOT_STATEFUL_STRATEGY_REPLAY',
                warning='Gross NIFTY points, not option P&L. Uniform reconstructed strategy replays; no manual interventions. Fixed entry/exit comparison, not a stateful replay of the VWAP-gated strategy. Five-minute futures candles reconstructed from exact one-minute data. Missing evidence is not counted as a blocked trade. The last month overlaps the three-month sample and includes the exploratory five days; it is not an untouched holdout.',
                baseline=stats(selected),comparisons=[comparison(selected,k) for k in ('alignment','alignment_and_slope')],daily=daily,coverage=checks,trades=selected)


def extended_run(args):
    end=date.fromisoformat(args.end_date)
    if end>=datetime.now(IST).date():raise ValueError('COMPLETED_PRIOR_SESSION_END_DATE_REQUIRED')
    start=month_start(end,max(args.months));warm_start=start-timedelta(days=70)
    root=args.output;root.mkdir(parents=True,exist_ok=True)
    gateway=ResearchData(root/'raw-provider-get',args.fetch_missing)
    try:
        with (root/'research.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            print(f'Windows ending {end}; earliest start {start}; GET-only research',flush=True)
            sessions,grouped=underlying_data(gateway,warm_start,end)
            target_days=[d for d in sessions if start<=date.fromisoformat(d)<=end]
            save_json(root/'session-calendar.json',dict(source='UPSTOX_NIFTY_DAILY_CANDLES',session_dates=target_days,warmup_start=str(warm_start)))
            if not target_days:raise ValueError('NO_TARGET_PROVIDER_SESSIONS')
            catalog,catalog_issues=future_catalog(gateway,start,end)
            save_json(root/'futures-catalog.json',dict(contracts=catalog,issues=catalog_issues))
            baselines,replay_issues,hashes=research_replays(sessions,grouped,start,end,root,args.expected_version,args.coverage_only)
            trades=[];coverage=[]
            for day in target_days:
                check=dict(session_date=day,alignment_coverage='INCOMPLETE',issues=[])
                try:
                    if day not in baselines:raise ValueError(replay_issues.get(day,'BASELINE_UNAVAILABLE'))
                    baseline=baselines[day];check['baseline_trades']=len(baseline)
                    if not baseline:
                        check.update(alignment_coverage='COMPLETE',status='NO_BASELINE_TRADES',slope_unknown=0)
                        coverage.append(check);continue
                    contract=resolve_front(catalog,day)
                    path=root/'futures-5m'/(day+'.json')
                    if path.exists():
                        saved=json.loads(path.read_text())
                        if saved['contract']['instrument_key']!=contract['instrument_key']:raise ValueError('CACHED_FRONT_CONTRACT_MISMATCH')
                        candles=saved['candles']
                    elif args.coverage_only:raise ValueError('FUTURES_SESSION_NOT_PREPARED')
                    else:
                        candles=fetch_session_future(gateway,contract,day)
                        save_json(path,dict(contract=contract,candles=candles,construction='EXACT_1M_TO_5M_NO_FILLING'))
                    results=[dict(evaluate(t,candles),session_date=day,strategy_version=args.expected_version,baseline_source='UNIFORM_VERSION_VERIFIED_RESEARCH_REPLAY',instrument_key=contract['instrument_key'],futures_cache=str(path)) for t in baseline]
                    known=sum(r.get('alignment') is not None for r in results)
                    check.update(status='AVAILABLE',alignment_coverage='COMPLETE' if known==len(results) else 'INCOMPLETE',alignment_known=known,slope_unknown=sum(r.get('alignment_and_slope') is None for r in results),trend_context=day_context(day,candles))
                    trades.extend(results)
                except Exception as exc:
                    check['issues'].append(str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
                    # Keep the baseline even when futures evidence is missing.
                    trades.extend(dict(t,session_date=day,strategy_version=args.expected_version,baseline_source='UNIFORM_VERSION_VERIFIED_RESEARCH_REPLAY',alignment=None,alignment_and_slope=None,vwap_issue=check['issues'][-1]) for t in baselines.get(day,[]))
                coverage.append(check)
                print(f'Coverage {day}: {check["alignment_coverage"]}',flush=True)
                save_json(root/'progress.json',dict(last_session=day,coverage=coverage,source_hashes=hashes,catalog_issues=catalog_issues,orders_sent=False))
            periods=[(f'{n}-month',month_start(end,n),end) for n in sorted(set(args.months))]
            if 1 in args.months and 3 in args.months:periods.append(('prior-two-months',month_start(end,3),month_start(end,1)-timedelta(days=1)))
            overview=['# HILEGA VWAP monthly comparison','',
                      '| Period | Dates | Covered sessions | Alignment coverage | Baseline points | Alignment points | Net change on matched coverage | Losing trades blocked | Winners blocked |',
                      '|---|---|---:|---|---:|---:|---:|---:|---:|']
            for name,first,last in periods:
                report=period_report(trades,coverage,first,last,args.expected_version,name)
                destination=root/name;destination.mkdir(exist_ok=True)
                save_json(destination/'report.json',report)
                (destination/'summary.md').write_text(markdown(report).replace('HILEGA VWAP last-five-session comparison',f'HILEGA VWAP {name} comparison',1))
                fields=['session_date','direction','entry_time','exit_time','entry_price','exit_price','points','vwap','futures_close','vwap_distance','vwap_slope_5m','alignment','alignment_and_slope','instrument_key','vwap_issue','slope_issue']
                with (destination/'trades.csv').open('w',newline='') as stream:
                    writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(report['trades'])
                a=report['comparisons'][0]
                overview.append(f'| {name} | {first} to {last} | {len(report["coverage"])} | {report["status"]} | {report["baseline"]["net_nifty_points"]:.2f} | {a["passed"]["net_nifty_points"]:.2f} | {a["improvement_points"]:.2f} | {a["blocked_losing_trades"]} | {a["blocked_winning_trades"]} |')
            overview+=['','Baseline includes all price-verifiable replay trades. Net change uses only matched VWAP coverage. See each period report for missing sessions, slope unknowns, blocked trades, and drawdowns.','',
                       'Observation only. Fixed-baseline filter classification; no orders or service changes. The one-month period is contained in the three-month period. The earlier two-month slice is shown separately, not labelled an untouched holdout.']
            text='\n'.join(overview)+'\n';(root/'comparison.md').write_text(text);print(text)
            print('REPORT ROOT:',root)
    finally:gateway.close()


class ExtendedChecks(ResearchChecks):
    def test_month_windows(self):
        self.assertEqual(str(month_start(date(2026,10,15),1)),'2026-09-16')
        self.assertEqual(str(month_start(date(2026,10,15),3)),'2026-07-16')
    def test_front_contract_does_not_use_current_for_unverified_past_month(self):
        with self.assertRaisesRegex(ValueError,'MANIFEST_MISSING'):
            resolve_front([dict(expiry='2026-10-27',instrument_key='OCT')],'2026-08-10')
    def test_expiry_day_and_roll(self):
        catalog=[dict(expiry='2026-08-25',instrument_key='A'),dict(expiry='2026-09-29',instrument_key='B')]
        self.assertEqual(resolve_front(catalog,'2026-08-25')['instrument_key'],'A')
        self.assertEqual(resolve_front(catalog,'2026-08-26')['instrument_key'],'B')
    def test_missing_futures_minute_is_not_filled(self):
        raw=[[(dt('2026-10-15T09:15:00+05:30')+timedelta(minutes=i)).isoformat(),100,101,99,100,10] for i in (0,1,2,4)]
        self.assertEqual(aggregate_futures(raw,'2026-10-15'),[])
    def test_exact_minute_aggregation(self):
        raw=[[(dt('2026-10-15T09:15:00+05:30')+timedelta(minutes=i)).isoformat(),100,101,99,100,10] for i in range(5)]
        result=aggregate_futures(raw,'2026-10-15')
        self.assertEqual(len(result),1);self.assertEqual(result[0][5],50)


def main():
    parser=argparse.ArgumentParser(description='Uniform current-strategy 1/3-month VWAP research. GET-only; no service changes.')
    parser.add_argument('--months',nargs='+',type=int,choices=[1,3],default=[1,3])
    parser.add_argument('--end-date',default='2026-10-15')
    parser.add_argument('--expected-version',default='five-minute-setup-1.2.0-pending-switch')
    parser.add_argument('--output',type=Path,default=Path('data/research/hilega-vwap-monthly-20261015'))
    parser.add_argument('--fetch-missing',action='store_true')
    parser.add_argument('--coverage-only',action='store_true')
    parser.add_argument('--test',action='store_true')
    args=parser.parse_args()
    if args.test:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ExtendedChecks))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    extended_run(args)



COHORT=json.loads("{\"BULLISH\":[\"2026-05-18\",\"2026-05-20\",\"2026-05-25\",\"2026-06-02\",\"2026-06-12\",\"2026-06-16\",\"2026-06-17\",\"2026-06-18\",\"2026-06-24\",\"2026-07-06\",\"2026-07-10\",\"2026-07-13\",\"2026-07-17\",\"2026-07-27\",\"2026-07-29\",\"2026-08-03\",\"2026-08-25\",\"2026-09-02\"],\"BEARISH\":[\"2026-05-12\",\"2026-05-19\",\"2026-05-29\",\"2026-06-01\",\"2026-06-23\",\"2026-06-29\",\"2026-07-07\",\"2026-07-08\",\"2026-07-14\",\"2026-07-16\",\"2026-07-22\",\"2026-08-18\",\"2026-08-24\",\"2026-08-26\",\"2026-08-27\",\"2026-09-03\",\"2026-09-07\",\"2026-09-08\"]}")
# Frozen cohort labels are attached AFTER strategy replay and never enter the engine.
import shutil


def cohort_validate(cohort):
    if set(cohort)!={'BULLISH','BEARISH'} or any(len(v)!=18 or len(set(v))!=18 for v in cohort.values()):
        raise ValueError('EXACT_18_PLUS_18_COHORT_REQUIRED')
    if set(cohort['BULLISH']) & set(cohort['BEARISH']):raise ValueError('COHORT_OVERLAP')
    for values in cohort.values():
        for value in values:date.fromisoformat(value)
    return {day:side for side,days in cohort.items() for day in days}


def cohort_report(trades, coverage, version):
    result=period_report(trades,coverage,date.fromisoformat(min(TARGET_DAYS)),date.fromisoformat(max(TARGET_DAYS)),version,'confirmed-36')
    result.update(model='HILEGA_VWAP_CONFIRMED36_RESEARCH_V1',cohort=COHORT,
                  cohort_usage='RETROSPECTIVE_REPORT_GROUPING_ONLY_NEVER_AN_ENTRY_INPUT',
                  warning='Historically selected trend sessions, not an independent holdout. Gross NIFTY points, not option P&L. Fixed-baseline filter comparison: original confirmed entry/exit retained; no delayed entries or stateful VWAP gating. Futures VWAP uses completed five-minute typical-price candles only. Unknown evidence is not a blocked trade.')
    result['groups']=[]
    for label in ('BULLISH','BEARISH','ALL'):
        days=set(TARGET_DAYS if label=='ALL' else COHORT[label])
        rows=[r for r in trades if r['session_date'] in days]
        for relationship in ('ALL_TRADES','WITH_SESSION_DIRECTION','AGAINST_SESSION_DIRECTION'):
            subset=[r for r in rows if relationship=='ALL_TRADES' or (r['direction']==TARGET_DAYS[r['session_date']])==(relationship=='WITH_SESSION_DIRECTION')]
            result['groups'].append(dict(session_group=label,trade_group=relationship,
                requested_sessions=len(days),complete_sessions=sum(c['session_date'] in days and c.get('alignment_coverage')=='COMPLETE' for c in coverage),
                baseline=stats(subset),comparisons=[comparison(subset,k) for k in ('alignment','alignment_and_slope')]))
    return result


def cohort_run(args):
    end=date.fromisoformat(max(TARGET_DAYS));start=date.fromisoformat(min(TARGET_DAYS))
    if end>=datetime.now(IST).date():raise ValueError('COMPLETED_PRIOR_SESSIONS_REQUIRED')
    root=args.output;root.mkdir(parents=True,exist_ok=True)
    with (root/'research.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        # Copy only research caches; originals remain unchanged. Replays are
        # subsequently checked against strategy/source/input fingerprints.
        if args.reuse_root and args.reuse_root.resolve()!=root.resolve():
            for folder in ('raw-provider-get','futures-5m','replays'):
                for source in (args.reuse_root/folder).glob('*.json'):
                    destination=root/folder/source.name
                    if not destination.exists():
                        destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
        save_json(root/'cohort.json',COHORT)
        gateway=ResearchData(root/'raw-provider-get',args.fetch_missing)
        try:
            sessions,grouped=underlying_data(gateway,start-timedelta(days=70),end)
            catalog,catalog_issues=future_catalog(gateway,start,end)
            save_json(root/'futures-catalog.json',dict(contracts=catalog,issues=catalog_issues))
            baselines,replay_issues,hashes=research_replays(sessions,grouped,start,end,root,args.expected_version,args.coverage_only)
            trades=[];coverage=[]
            for day,label in sorted(TARGET_DAYS.items()):
                check=dict(session_date=day,session_label=label,alignment_coverage='INCOMPLETE',issues=[])
                try:
                    if day not in sessions:raise ValueError('FROZEN_SESSION_NOT_IN_PROVIDER_CALENDAR')
                    if day not in baselines:raise ValueError(replay_issues.get(day,'BASELINE_UNAVAILABLE'))
                    baseline=baselines[day];check['baseline_trades']=len(baseline)
                    if not baseline:
                        check.update(status='NO_BASELINE_TRADES',alignment_coverage='COMPLETE',slope_unknown=0)
                    else:
                        contract=resolve_front(catalog,day);path=root/'futures-5m'/(day+'.json')
                        if path.exists():
                            saved=json.loads(path.read_text())
                            if saved['contract']['instrument_key']!=contract['instrument_key']:raise ValueError('CACHED_FRONT_CONTRACT_MISMATCH')
                            candles=saved['candles']
                        elif args.coverage_only:raise ValueError('FUTURES_SESSION_NOT_PREPARED')
                        else:
                            candles=fetch_session_future(gateway,contract,day)
                            save_json(path,dict(contract=contract,candles=candles,construction='EXACT_1M_TO_5M_NO_FILLING'))
                        results=[dict(evaluate(t,candles),session_date=day,session_label=label,strategy_version=args.expected_version,
                                      baseline_source='UNIFORM_VERSION_VERIFIED_RESEARCH_REPLAY',instrument_key=contract['instrument_key'],futures_cache=str(path)) for t in baseline]
                        known=sum(r.get('alignment') is not None for r in results)
                        check.update(status='AVAILABLE',alignment_coverage='COMPLETE' if known==len(results) else 'INCOMPLETE',alignment_known=known,
                                     slope_unknown=sum(r.get('alignment_and_slope') is None for r in results),trend_context=day_context(day,candles))
                        trades.extend(results)
                except Exception as exc:
                    check['issues'].append(str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
                    trades.extend(dict(t,session_date=day,session_label=label,strategy_version=args.expected_version,
                                       baseline_source='UNIFORM_VERSION_VERIFIED_RESEARCH_REPLAY',alignment=None,alignment_and_slope=None,
                                       vwap_issue=check['issues'][-1]) for t in baselines.get(day,[]))
                coverage.append(check)
                save_json(root/'progress.json',dict(coverage=coverage,source_hashes=hashes,catalog_issues=catalog_issues,orders_sent=False))
                print(day,label,check['alignment_coverage'],check['issues'],flush=True)
            trades.sort(key=lambda r:dt(r['entry_time']))
            report=cohort_report(trades,coverage,args.expected_version)
            report.update(source_hashes=hashes,catalog_issues=catalog_issues,orders_sent=False)
            save_json(root/'report.json',report)
            lines=['# VWAP alignment on frozen 18 bullish + 18 bearish sessions','',report['warning'],'',
                   'Status: '+report['status'],'',
                   '| Sessions | Trade direction | Coverage | Current points | VWAP points | Change | Taken | Blocked | Losers blocked | Winners blocked | Unknown |',
                   '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
            for group in report['groups']:
                c=group['comparisons'][0]
                lines.append(f"| {group['session_group']} | {group['trade_group']} | {group['complete_sessions']}/{group['requested_sessions']} | {c['baseline_same_coverage']['net_nifty_points']:.2f} | {c['passed']['net_nifty_points']:.2f} | {c['improvement_points']:.2f} | {c['passed']['priced_trades']} | {c['blocked']['priced_trades']} | {c['blocked_losing_trades']} | {c['blocked_winning_trades']} | {c['excluded_unknown_rule']} |")
            lines+=['',markdown(report)]
            text='\n'.join(lines)+'\n';(root/'summary.md').write_text(text)
            fields=['session_date','session_label','direction','entry_time','exit_time','entry_price','exit_price','points','vwap','futures_close','vwap_distance','alignment','alignment_and_slope','instrument_key','vwap_issue']
            with (root/'trades.csv').open('w',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(trades)
            print(text);print('REPORT:',root/'report.json')
            return report['status']=='COMPLETE'
        finally:gateway.close()


class CohortChecks(ExtendedChecks):
    def test_exact_frozen_cohort(self):
        self.assertEqual(len(cohort_validate(COHORT)),36)
    def test_duplicate_cohort_rejected(self):
        bad={k:list(v) for k,v in COHORT.items()};bad['BULLISH'][0]=bad['BULLISH'][1]
        with self.assertRaises(ValueError):cohort_validate(bad)
    def test_missing_session_cannot_be_complete(self):
        r=cohort_report([], [dict(session_date=d,alignment_coverage='INCOMPLETE',issues=['MISSING']) for d in TARGET_DAYS], 'TEST')
        self.assertEqual(r['status'],'INCOMPLETE')
        self.assertEqual(len(r['coverage']),36)


def main():
    p=argparse.ArgumentParser(description='Frozen 36-session VWAP alignment comparison. GET-only research; no orders or service changes.')
    p.add_argument('--expected-version',default='five-minute-setup-1.2.0-pending-switch')
    p.add_argument('--output',type=Path,default=Path('data/research/hilega-vwap-confirmed36-20261016'))
    p.add_argument('--reuse-root',type=Path,default=Path('data/research/hilega-vwap-monthly-20261015'))
    p.add_argument('--fetch-missing',action='store_true')
    p.add_argument('--coverage-only',action='store_true')
    p.add_argument('--test',action='store_true')
    args=p.parse_args()
    if args.test:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CohortChecks))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    raise SystemExit(0 if cohort_run(args) else 2)


TARGET_DAYS=cohort_validate(COHORT)

if __name__=='__main__':main()
