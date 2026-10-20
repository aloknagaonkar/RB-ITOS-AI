"""Read-only bullish trade screen from V20 replay outputs; never places orders.

Fixed-trade classification only: filtering does not replay changed strategy state.
Use --root repeatedly for the historical batch and newer single-day replay.
"""
import argparse
import calendar
import csv
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
import unittest

POLICY='FRESH_AND_EMA10_ENTRY'
MODEL='FRESH_DIRECT_5M_RSI40_60_EMA_TOUCH_WAIT_V20'
RULES=[('UNFILTERED',0,0)]
RULES += [('SIGNAL_GAP_GE_'+str(g),g,0) for g in (1,2,3,4,5)]
RULES += [('SIGNAL_STRENGTH_GE_'+str(s),0,s) for s in (1,1.25,1.5)]
RULES += [('SIGNAL_GAP_GE_3_AND_STRENGTH_GE_1',3,1)]

def stats(rows):
    points=[float(r['points']) for r in rows]
    return dict(trades=len(points),winning_points=sum(max(p,0) for p in points),
                losing_points=sum(min(p,0) for p in points),net_points=sum(points))

def classify(rows,gap,strength):
    taken=[];blocked=[];unknown=[]
    for row in rows:
        values=[row.get('signal_gap'),row.get('signal_strength')]
        if any(v is None or not math.isfinite(float(v)) for v in values):unknown.append(row)
        elif values[0]>=gap and values[1]>=strength:taken.append(row)
        else:blocked.append(row)
    return taken,blocked,unknown

def frame_index(audit):
    out={}
    for row in audit:
        if row.get('completed_5m_indicators') and row.get('five_minute_changes'):
            at=row['checkpoint']
            if at in out and out[at]!=row:raise ValueError('CONFLICTING_5M_FRAME:'+at)
            out[at]=row
    return out

def features(frame):
    v=frame['completed_5m_indicators'];d=frame['five_minute_changes']
    return dict(rsi=v['rsi9'],ema=v['ema3'],wma=v['wma21'],strength=d['wma21'],
                gap=v['ema3']-v['wma21'],expansion=d['ema3']-d['wma21'],
                rsi_change=d['rsi9'],ema_change=d['ema3'],wma_change=d['wma21'])

def extract(day,session):
    policy=session[POLICY]
    if not policy.get('research_entry_rules',{}).get('retain_failed_followup_only_on_ema10_touch'):
        raise ValueError('EMA_TOUCH_POLICY_METADATA_REQUIRED:'+day)
    frames=frame_index(session['EXISTING']['audit']);rows=[];steps=[]
    for trade in policy['trades']:
        if trade['direction']!='BULLISH':continue
        entry=trade['entry_time']
        events=[e for e in policy.get('policy_events',[]) if e.get('event')=='FOLLOWUP_CANDLE_CHECK'
                and e.get('passed') is True and e.get('direction')=='BULLISH' and e.get('time')==entry
                and e.get('setup_available')==trade['signal_time']]
        signals={e.get('signal_time') for e in events}
        if len(signals)!=1 or None in signals:raise ValueError('EXACT_SIGNAL_IDENTITY_REQUIRED:'+entry)
        signal=signals.pop();sf=features(frames[signal]);ef=features(frames[entry])
        row=dict(date=day,setup=trade['signal_time'][11:16],signal=signal[11:16],
                 entry=entry[11:16],exit=trade['exit_time'][11:16],points=float(trade['points']))
        row.update({'signal_'+k:v for k,v in sf.items()})
        row.update({'entry_'+k:v for k,v in ef.items()})
        row.update({'rise_'+k:ef[k]-sf[k] for k in ('rsi','ema','wma')})
        interval=[(at,features(f)) for at,f in sorted(frames.items()) if signal<=at<=entry]
        expected=int((datetime.fromisoformat(entry)-datetime.fromisoformat(signal)).total_seconds()/300)+1
        if len(interval)!=expected:raise ValueError('INCOMPLETE_SIGNAL_TO_ENTRY_FRAMES:'+entry)
        for k in ('rsi','ema','wma'):
            row[k+'_rising_each_candle']=all(f[k+'_change']>0 for _,f in interval)
        rows.append(row)
        for at,f in interval:steps.append(dict(date=day,trade_entry=row['entry'],time=at[11:16],stage='SIGNAL' if at==signal else 'ENTRY' if at==entry else 'WAIT',**f))
    return rows,steps

def fmt(value):
    if isinstance(value,float):return f'{value:+.3f}'
    return str(value)

def table(title,rows,columns):
    lines=['',title,'','| '+' | '.join(columns)+' |','|'+'---|'*len(columns)]
    lines += ['| '+' | '.join(fmt(r.get(k,'—')) for k in columns)+' |' for r in rows]
    return lines

def previous_month(value):
    year=value.year-(value.month==1);month=12 if value.month==1 else value.month-1
    return value.replace(year=year,month=month,day=min(value.day,calendar.monthrange(year,month)[1]))

class Checks(unittest.TestCase):
    def test_winners_forgone_and_losses_avoided_both_counted(self):
        rows=[dict(points=100,signal_gap=2,signal_strength=1),dict(points=-104.55,signal_gap=.555,signal_strength=.937),dict(points=20,signal_gap=4,signal_strength=1.2)]
        taken,blocked,unknown=classify(rows,3,0)
        self.assertEqual(stats(taken)['net_points'],20)
        self.assertAlmostEqual(stats(blocked)['net_points'],-4.55)
        self.assertEqual(stats(blocked)['winning_points'],100)
        self.assertFalse(unknown)
    def test_equality_passes_and_unknown_is_not_blocked(self):
        taken,blocked,unknown=classify([dict(points=1,signal_gap=3,signal_strength=1),dict(points=2,signal_gap=None,signal_strength=1)],3,1)
        self.assertEqual(len(taken),1);self.assertFalse(blocked);self.assertEqual(len(unknown),1)
    def test_previous_calendar_month(self):
        self.assertEqual(previous_month(date(2026,10,19)),date(2026,9,19))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,action='append',default=[])
    ap.add_argument('--end-date',default='2026-10-19')
    ap.add_argument('--output',type=Path,default=Path('data/research/hilega-bullish-month-20261019'))
    ap.add_argument('--test',action='store_true');args=ap.parse_args()
    if args.test:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    if not args.root:ap.error('Supply --root for V20 replay outputs')
    end=date.fromisoformat(args.end_date);start=previous_month(end)
    sources={};errors=[]
    for root in args.root:
        report=json.loads((root/'report.json').read_text())
        if report.get('model')!=MODEL:raise ValueError('V20_MODEL_REQUIRED:'+str(root))
        for day in report['session_dates']:
            if not start.isoformat()<=day<=end.isoformat():continue
            proof=report.get('provenance',{}).get(day,{})
            if proof.get('baseline_parity',{}).get('status')!='PASS':
                errors.append(day+':BASELINE_NOT_VERIFIED');continue
            body=(root/'sessions'/(day+'.json')).read_text()
            if day in sources and sources[day][0]!=body:raise ValueError('CONFLICTING_SESSION:'+day)
            sources[day]=(body,str(root))
    if end.isoformat() not in sources:errors.append('END_SESSION_MISSING')
    # Validate coverage against the saved research trading calendar, plus newer roots.
    import hilega_vwap_confirmed36_research as support
    from hilega_vwap_wait_alignment_research import source_data
    root=Path('data/research/hilega-vwap-monthly-20261015')
    parent=json.loads((root/'3-month/report.json').read_text())
    days,_=source_data(root,parent,support)
    required={d for d in days if start.isoformat()<=d<=min(end.isoformat(),'2026-10-15')}
    # The frozen calendar ends Oct15; Oct16/19 are known subsequent research sessions.
    required.update(d for d in ('2026-10-16','2026-10-19') if start.isoformat()<=d<=end.isoformat())
    errors.extend('MISSING_SESSION:'+d for d in sorted(required-set(sources)))
    if end>date(2026,10,19):errors.append('CALENDAR_EXTENSION_REQUIRED_AFTER_2026_10_19')
    rows=[];steps=[]
    for day,(body,_) in sorted(sources.items()):
        r,s=extract(day,json.loads(body));rows.extend(r);steps.extend(s)
    comparisons=[]
    for name,gap,strength in RULES:
        taken,blocked,unknown=classify(rows,gap,strength);ts=stats(taken);bs=stats(blocked)
        target=[r for r in rows if r['date']=='2026-10-19' and r['entry']=='09:45']
        comparisons.append(dict(rule=name,taken=len(taken),blocked=len(blocked),unknown=len(unknown),
            passed_points=ts['net_points'],loss_points_avoided=-bs['losing_points'],winning_points_forgone=bs['winning_points'],
            winners_blocked=sum(r['points']>0 for r in blocked),losers_blocked=sum(r['points']<0 for r in blocked),
            net_change=-bs['net_points'],oct19_0945='BLOCK' if target and target[0] in blocked else 'PASS' if target and target[0] in taken else 'UNAVAILABLE'))
    lines=['# Bullish one-month gap and slope comparison','',f'Period: {start} through {end}; status: '+('INCOMPLETE' if errors else 'COMPLETE'),
           '', 'Latest V20 EMA10-touch policy. Gross NIFTY points; costs excluded. Fixed-trade screening, not stateful filtered replay. Thresholds are exploratory and evaluated on already examined data. No live changes.',
           '',f'Included sessions: {len(sources)}. Bullish trades: {len(rows)}. Issues: {errors}',
           '', 'All filters use signal-time values, never future entry values. Positive-only tables are descriptive; filter comparisons include every bullish loser too.']
    columns=['date','setup','signal','entry','exit','points','signal_wma','signal_strength','signal_gap','signal_expansion','entry_wma','entry_strength','entry_gap','rise_rsi','rise_ema','rise_wma']
    lines+=table('## Profitable bullish trades',[r for r in rows if r['points']>0],columns)
    lines+=table('## Losing bullish trades',[r for r in rows if r['points']<0],columns)
    lines+=table('## Filter trade-offs',comparisons,['rule','taken','blocked','unknown','passed_points','losers_blocked','loss_points_avoided','winners_blocked','winning_points_forgone','net_change','oct19_0945'])
    lines+=table('## Candle-by-candle RSI / EMA3 / WMA magnitude',steps,['date','trade_entry','time','stage','rsi','ema','wma','rsi_change','ema_change','wma_change','gap','expansion'])
    args.output.mkdir(parents=True,exist_ok=True)
    for name,data in [('bullish-trades.csv',rows),('candle-values.csv',steps),('filter-comparison.csv',comparisons)]:
        fields=list(data[0]) if data else ['date']
        with (args.output/name).open('w',newline='') as stream:
            w=csv.DictWriter(stream,fields);w.writeheader();w.writerows(data)
    (args.output/'report.json').write_text(json.dumps(dict(status='INCOMPLETE' if errors else 'COMPLETE',start=str(start),end=str(end),issues=errors,sessions=sorted(sources),trades=rows,comparisons=comparisons,orders_sent=False),indent=2)+'\n')
    (args.output/'summary.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines[:7]));print('SUMMARY:',args.output/'summary.md')

if __name__=='__main__':main()
