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
                if event.get('points') is not None and abs(number(event['points'])-points)>1e-5:
                    raise ValueError('EXIT_POINTS_MISMATCH')
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
                warning='Gross NIFTY points, not option P&L. Original confirmed entry and exit times retained. Filtering may change future strategy state; this report does not model that effect. Five sessions cannot establish a robust edge. Reconstructed futures five-minute typical-price VWAP, not index VWAP.',
                rules=dict(alignment='Bullish: completed futures close > VWAP; bearish: close < VWAP. At VWAP fails.',alignment_and_slope='Alignment plus cumulative session VWAP rising over the previous completed five-minute boundary for bullish, falling for bearish. Flat slope fails; unavailable slope is unknown, not blocked.'),
                coverage=coverage,baseline=stats(all_trades),comparisons=[comparison(all_trades,key) for key in ('alignment','alignment_and_slope')],daily=daily,trades=all_trades)
    path=output/'report.json';path.write_text(json.dumps(report,indent=2)+'\n')
    fields=['session_date','direction','setup_time','entry_time','exit_time','entry_price','exit_price','points','exit_reason','vwap','futures_close','vwap_distance','candle_available_at','vwap_slope_5m','alignment','alignment_and_slope','baseline_source','strategy_version','vwap_issue','slope_issue','coverage_issue']
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


if __name__=='__main__':main()
