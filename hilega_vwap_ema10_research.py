"""Offline EMA10 exceptions to VWAP alignment. Reads research caches only.
No broker imports, provider requests, service controls, or execution changes.
"""
import argparse
import csv
import hashlib
import json
import math
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

IST=ZoneInfo('Asia/Kolkata')
VERSION='five-minute-setup-1.2.0-pending-switch'
RULES=('alignment','vwap_or_ema10_side','vwap_or_ema10_side_and_slope')


def dt(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
    return result.astimezone(IST)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()


def cached(root,path):
    request=dict(path=path,params={})
    record=json.loads((root/'raw-provider-get'/(fingerprint(request)+'.json')).read_text())
    if record['request']!=request or fingerprint(record['body'])!=record['body_sha256']:
        raise ValueError('RAW_CACHE_IDENTITY_OR_HASH_MISMATCH')
    return record['body']['data']['candles']


def bars_for(day,minutes):
    start=dt(day+'T09:15:00+05:30');bars=[]
    for i in range(75):
        at=start+timedelta(minutes=5*i);keys=[at+timedelta(minutes=n) for n in range(5)]
        if not all(key in minutes for key in keys):raise ValueError('INCOMPLETE_NIFTY_1M_PATH:'+day)
        bars.append(dict(available_at=at+timedelta(minutes=5),close=minutes[keys[-1]][4]))
    return bars


def load_minutes(root,report):
    start=datetime.fromisoformat(report['start_date']).date()-timedelta(days=70)
    end=datetime.fromisoformat(report['end_date']).date()
    calendar_path=root/'session-calendar.json'
    if calendar_path.exists():
        metadata=json.loads(calendar_path.read_text())
        start=datetime.fromisoformat(metadata['warmup_start']).date()
        end=datetime.fromisoformat(max(metadata['session_dates'])).date()
    key=quote('NSE_INDEX|Nifty 50',safe='')
    calendar=cached(root,f'/v3/historical-candle/{key}/days/1/{end}/{start}')
    sessions=sorted({dt(r[0]).date().isoformat() for r in calendar if start<=dt(r[0]).date()<=end})
    minutes={};cursor=start
    while cursor<=end:
        last=min(end,cursor+timedelta(days=27))
        for raw in cached(root,f'/v3/historical-candle/{key}/minutes/1/{last}/{cursor}'):
            at=dt(raw[0])
            if not '09:15'<=at.strftime('%H:%M')<'15:30':continue
            if at.second or at.microsecond:raise ValueError('NON_MINUTE_TIMESTAMP')
            values=[float(v) for v in raw[1:5]]
            if not all(math.isfinite(v) and v>0 for v in values):raise ValueError('INVALID_OHLC')
            o,h,l,c=values
            if h<max(o,l,c) or l>min(o,h,c):raise ValueError('INVALID_OHLC')
            row=[at.isoformat(),*values]
            if at in minutes and minutes[at]!=row:raise ValueError('CONFLICTING_RAW_MINUTE')
            minutes[at]=row
        cursor=last+timedelta(days=1)
    return sessions,minutes


def ema_frames(day,sessions,minutes):
    warm=[d for d in sessions if d<day][-30:]
    if len(warm)<20:raise ValueError('TWENTY_PRIOR_WARMUP_SESSIONS_REQUIRED')
    ema=None;previous=None;frames=[]
    for session in warm+[day]:
        for bar in bars_for(session,minutes):
            previous=ema
            ema=bar['close'] if ema is None else (2/11)*bar['close']+(9/11)*ema
            if session==day:
                frames.append(dict(candle_available_at=bar['available_at'].isoformat(),
                                   nifty_5m_close=bar['close'],ema10=ema,previous_ema10=previous,
                                   ema10_change=ema-previous if previous is not None else None,
                                   warmup_sessions=len(warm)))
    return frames


def exception_rules(alignment,direction,close,ema,slope):
    if direction not in ('BULLISH','BEARISH'):raise ValueError('INVALID_DIRECTION')
    side=close>ema if direction=='BULLISH' else close<ema
    increasing=slope>0 if direction=='BULLISH' else slope<0
    # Unknown VWAP cannot be relabelled an opposing VWAP signal.
    return dict(ema10_side_pass=side,ema10_slope_pass=increasing,
                vwap_or_ema10_side=True if alignment is True else side if alignment is False else None,
                vwap_or_ema10_side_and_slope=True if alignment is True else side and increasing if alignment is False else None)


def total(rows):return round(sum(r['points'] for r in rows),4)


def comparison(rows,rule):
    known=[r for r in rows if r.get(rule) is not None]
    passed=[r for r in known if r[rule]];blocked=[r for r in known if not r[rule]]
    restored=[r for r in known if r['alignment'] is False and r[rule] is True]
    winners=[r for r in restored if r['points']>0];losers=[r for r in restored if r['points']<0]
    baseline_vwap=[r for r in known if r['alignment'] is True]
    return dict(rule=rule,comparable_trades=len(known),unknown=len(rows)-len(known),taken=len(passed),blocked=len(blocked),
                current_points=total(known),vwap_same_coverage_points=total(baseline_vwap),passed_points=total(passed),
                net_change_vs_vwap=round(total(passed)-total(baseline_vwap),4),
                winners_recovered=len(winners),profit_recovered=total(winners),losers_reintroduced=len(losers),
                losses_reintroduced=round(-total(losers),4),breakevens_reintroduced=sum(r['points']==0 for r in restored))


def evaluate_report(root,report):
    if report.get('strategy_version')!=VERSION:raise ValueError('STRATEGY_VERSION_MISMATCH')
    sessions,minutes=load_minutes(root,report);frames={};issues={};rows=[]
    for trade in sorted(report['trades'],key=lambda r:dt(r['entry_time'])):
        row=dict(trade);day=row['session_date'];at=dt(row['entry_time'])
        if row.get('points') is None or not math.isfinite(float(row['points'])):raise ValueError('FINITE_PRICED_TRADE_REQUIRED')
        expected=(row['exit_price']-row['entry_price'])*(1 if row['direction']=='BULLISH' else -1)
        if abs(expected-row['points'])>1e-5:raise ValueError('TRADE_POINTS_MISMATCH')
        try:
            if day not in frames and day not in issues:
                try:frames[day]=ema_frames(day,sessions,minutes)
                except (ValueError,KeyError) as exc:issues[day]=str(exc)
            if day in issues:raise ValueError(issues[day])
            eligible=[f for f in frames[day] if dt(f['candle_available_at'])<=at]
            if not eligible:raise ValueError('NO_COMPLETED_CURRENT_SESSION_5M_CANDLE')
            frame=eligible[-1]
            if not 0<=(at-dt(frame['candle_available_at'])).total_seconds()<300:raise ValueError('STALE_EMA10_CANDLE')
            row.update(frame)
            row.update(exception_rules(row.get('alignment'),row['direction'],frame['nifty_5m_close'],frame['ema10'],frame['ema10_change']))
            row['ema10_exception_reason']='VWAP_ALREADY_ALIGNED' if row.get('alignment') is True else 'EMA10_SIDE_EXCEPTION' if row['vwap_or_ema10_side'] else 'EMA10_SIDE_NOT_ALIGNED_OR_VWAP_UNKNOWN'
        except (ValueError,KeyError,TypeError) as exc:
            row.update(ema10_issue=str(exc),vwap_or_ema10_side=True if row.get('alignment') is True else None,
                       vwap_or_ema10_side_and_slope=True if row.get('alignment') is True else None)
        rows.append(row)
    return rows


class Checks(unittest.TestCase):
    def test_bullish_exception(self):self.assertTrue(exception_rules(False,'BULLISH',101,100,1)['vwap_or_ema10_side'])
    def test_bearish_exception(self):self.assertTrue(exception_rules(False,'BEARISH',99,100,-1)['vwap_or_ema10_side'])
    def test_side_without_slope(self):
        r=exception_rules(False,'BULLISH',101,100,-1)
        self.assertTrue(r['vwap_or_ema10_side']);self.assertFalse(r['vwap_or_ema10_side_and_slope'])
    def test_equality_not_exception(self):self.assertFalse(exception_rules(False,'BULLISH',100,100,0)['vwap_or_ema10_side'])
    def test_aligned_never_removed(self):self.assertTrue(exception_rules(True,'BULLISH',99,100,-1)['vwap_or_ema10_side'])
    def test_unknown_vwap_stays_unknown(self):self.assertIsNone(exception_rules(None,'BULLISH',101,100,1)['vwap_or_ema10_side'])
    def test_recovered_loser_counted(self):
        r=comparison([dict(points=10,alignment=False,vwap_or_ema10_side=True),dict(points=-15,alignment=False,vwap_or_ema10_side=True)],'vwap_or_ema10_side')
        self.assertEqual((r['winners_recovered'],r['losers_reintroduced'],r['net_change_vs_vwap']),(1,1,-5))
    def test_missing_minutes_rejected(self):
        with self.assertRaises(ValueError):bars_for('2026-07-17',{})
    def test_completed_boundary(self):
        day='2026-07-17';start=dt(day+'T09:15:00+05:30')
        minutes={start+timedelta(minutes=i):['',100,100,100,100] for i in range(375)}
        bars=bars_for(day,minutes)
        self.assertEqual(bars[0]['available_at'],dt(day+'T09:20:00+05:30'))
        self.assertFalse(any(b['available_at']<=dt(day+'T09:19:00+05:30') for b in bars))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--research-root',type=Path,action='append')
    p.add_argument('--output',type=Path,default=Path('data/research/hilega-vwap-ema10-exception-20261016'))
    p.add_argument('--test',action='store_true');args=p.parse_args()
    if args.test:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    if not args.research_root:p.error('--research-root required; repeat for cohort and monthly research')
    output=args.output;output.mkdir(parents=True,exist_ok=True);results=[];failures=[]
    for root in args.research_root:
        paths=[root/'report.json'] if (root/'report.json').exists() else [root/name/'report.json' for name in ('1-month','3-month','prior-two-months')]
        for path in paths:
            try:
                report=json.loads(path.read_text());rows=evaluate_report(root,report)
                name=report.get('period',path.parent.name);groups={'ALL':rows}
                for side in ('BULLISH','BEARISH'):
                    if any(r.get('session_label')==side for r in rows):groups[side+'_SESSIONS']=[r for r in rows if r.get('session_label')==side]
                item=dict(source_report=str(path),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),period=name,
                          status='COMPLETE' if report.get('status')=='COMPLETE' and all(r.get('vwap_or_ema10_side') is not None for r in rows) else 'INCOMPLETE',
                          comparisons={g:[comparison(v,k) for k in RULES] for g,v in groups.items()},trades=rows)
                results.append(item)
            except (ValueError,KeyError,TypeError,OSError) as exc:failures.append(dict(source_report=str(path),error=str(exc)))
    payload=dict(model='HILEGA_VWAP_EMA10_EXCEPTION_RESEARCH_V1',observation_only=True,orders_sent=False,
                 status='COMPLETE' if results and not failures and all(r['status']=='COMPLETE' for r in results) else 'INCOMPLETE',
                 ema_definition='NIFTY price EMA10, alpha 2/11, first close seed, 30 prior sessions where available (minimum 20), continuous across sessions; completed 5m only.',
                 warning='Exploratory fixed-baseline classification, not a stateful replay or option P&L. Recovered winners and reintroduced losers both counted. Cohort is retrospectively selected; periods overlap.',
                 results=results,failures=failures)
    (output/'report.json').write_text(json.dumps(payload,indent=2)+'\n')
    lines=['# VWAP with EMA10 exception','',payload['ema_definition'],'',payload['warning'],'',
           '| Period | Group | Rule | Known trades | Unknown | Current pts | VWAP pts, matched | Rule pts | Change vs VWAP | Taken | Blocked | Winners recovered | Losers reintroduced |',
           '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for result in results:
        for group,comparisons in result['comparisons'].items():
            for c in comparisons:
                lines.append(f"| {result['period']} | {group} | {c['rule']} | {c['comparable_trades']} | {c['unknown']} | {c['current_points']:.2f} | {c['vwap_same_coverage_points']:.2f} | {c['passed_points']:.2f} | {c['net_change_vs_vwap']:.2f} | {c['taken']} | {c['blocked']} | {c['winners_recovered']} | {c['losers_reintroduced']} |")
    lines+=['','Status: '+payload['status'],'','Failures: '+json.dumps(failures)]
    (output/'summary.md').write_text('\n'.join(lines)+'\n');print('\n'.join(lines));print('REPORT:',output/'report.json')
    raise SystemExit(0 if payload['status']=='COMPLETE' else 2)


if __name__=='__main__':main()
