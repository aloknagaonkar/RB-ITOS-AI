"""Read-only bearish gap/momentum screen: 10 sessions, 30, three months.

Uses saved bullish-2/2 stateful trades. Does not change strategy or send orders.
"""
import argparse
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
import unittest
import hilega_bearish_gap_magnitude_research as bear
from hilega_bullish_month_gap_research import features, frame_index, stats

def momentum(signal,entry,path):
    out={}
    for key in ('rsi','ema','wma'):
        prior=signal[key]-signal[key+'_change']
        out['prior_'+key]=prior
        out['full_fall_'+key]=prior-entry[key]
        out[key+'_falling_each_candle']=all(f[key+'_change']<0 for _,f in path)
    out['average_wma_decline']=out['full_fall_wma']/len(path)
    out['signal_strength']=-signal['strength'];out['entry_strength']=-entry['strength']
    out['entry_wma_acceleration']=(-entry['strength'])-(-path[-2][1]['strength'])
    out['separation_change']=(entry['wma']-entry['ema'])-(signal['wma']-signal['ema'])
    out['rsi_ema_separation_change']=(entry['ema']-entry['rsi'])-(signal['ema']-signal['rsi'])
    return out

def extract(day,session):
    rows=bear.extract(day,session);frames=frame_index(session['EXISTING']['audit']);steps=[]
    for row in rows:
        signal=row['signal'];entry=row['entry']
        path=[(at,features(f)) for at,f in sorted(frames.items()) if signal<=at<=entry]
        count=int((datetime.fromisoformat(entry)-datetime.fromisoformat(signal)).total_seconds()/300)+1
        if len(path)!=count or count<2:raise ValueError('INCOMPLETE_SIGNAL_ENTRY_GRID:'+entry)
        for index,(at,f) in enumerate(path):
            expected=datetime.fromisoformat(signal)+timedelta(minutes=5*index)
            if datetime.fromisoformat(at)!=expected:raise ValueError('NON_CONSECUTIVE_COMPLETED_FRAMES:'+entry)
            for key in ('rsi','ema','wma','rsi_change','ema_change','wma_change'):
                if not math.isfinite(float(f[key])):raise ValueError('NONFINITE_FRAME:'+at)
        sf=path[0][1];ef=path[-1][1];row.update(momentum(sf,ef,path))
        prior_at=(datetime.fromisoformat(signal)-timedelta(minutes=5)).isoformat()
        steps.append(dict(date=day,entry=entry,time=prior_at,stage='PRE_SIGNAL',
            rsi=row['prior_rsi'],ema=row['prior_ema'],wma=row['prior_wma'],
            rsi_change=None,ema_change=None,wma_change=None,strength=None,
            gap=row['prior_wma']-row['prior_ema'],expansion=None))
        for at,f in path:
            steps.append(dict(date=day,entry=entry,time=at,stage='SIGNAL' if at==signal else 'ENTRY' if at==entry else 'WAIT',
                **dict(f,strength=-f['strength'],gap=-f['gap'],expansion=-f['expansion'])))
    return rows,steps

RULES=[('NO_EXTRA_FILTER',None,None)]
RULES += [(f'GAP_GE_{g}','gap',g) for g in (1.5,2,2.5,3)]
RULES += [(f'FULL_WMA_DECLINE_GE_{m}','full_fall_wma',m) for m in (1.8,2,2.2)]
RULES += [('SUSTAINED_WMA_DECLINE','wma_falling_each_candle',True),
          ('SUSTAINED_RSI_DECLINE','rsi_falling_each_candle',True),
          ('SUSTAINED_EMA3_DECLINE','ema_falling_each_candle',True),
          ('ENTRY_STRENGTH_GE_075','entry_strength',.75),
          ('AVERAGE_WMA_DECLINE_GE_1','average_wma_decline',1),
          ('RSI_EMA_SEPARATION_NOT_SHRINKING','rsi_ema_separation_change',0),
          ('WMA_DECLINE_ACCELERATING_AT_ENTRY','entry_wma_acceleration','POSITIVE')]

def passed(row,field,value):
    if field is None:return True
    actual=row.get(field)
    if isinstance(value,bool):return actual is value
    if actual is None or not math.isfinite(float(actual)):raise ValueError('UNKNOWN_FILTER_VALUE:'+field)
    return actual>0 if value=='POSITIVE' else actual>=value

def outcomes(rows,field,value,gap=None):
    take=[];block=[]
    for r in rows:
        ok=passed(r,field,value) and (gap is None or r['gap']>=gap)
        (take if ok else block).append(r)
    return take,block

def fmt(value):return '—' if value is None else f'{value:.3f}'

def write(output,days,rows,steps,proof):
    lines=['# Bearish gap and momentum — staged screening','',
        'Source: saved stateful bullish gap>=2 / WMA magnitude>=2 strategy, without an extra bearish filter. '
        'Fixed-trade screening only: rejected entries do not replay future strategy state. '
        'All thresholds use information available by entry. Gross NIFTY points, costs excluded. '
        'Previously examined data; no independent holdout or live changes.','',
        'Full downward magnitude = WMA immediately before qualified signal minus entry WMA. '
        'Strength = negative of WMA change. Bearish gap = WMA21 minus EMA3 of RSI9. '
        'Expansion = current bearish gap minus previous bearish gap. '
        'Sustained decline includes signal and every waiting/entry candle; flat readings fail.','']
    decisions=[]
    for label,count in [('LAST_10',10),('LAST_30',30),('THREE_MONTHS',None)]:
        selected_days=days[-count:] if count else days
        if count and len(selected_days)!=count:raise ValueError('INSUFFICIENT_SESSIONS:'+label)
        rr=[r for r in rows if r['date'] in selected_days];baseline=stats(rr)
        lines += [f'## {label}: {selected_days[0]} through {selected_days[-1]}','',
            f"Sessions: {len(selected_days)}; bearish trades: {len(rr)}; baseline net: {baseline['net_points']:+.2f}.",'',
            '| Rule | Passed | Blocked winners | Blocked losers | Passed net points | Loss points excluded | Winning points excluded | Net change |',
            '|---|---:|---:|---:|---:|---:|---:|---:|']
        tests=[(name,field,value,None) for name,field,value in RULES]
        tests += [(f'GAP2p5_AND_{name}',field,value,2.5) for name,field,value in RULES if field not in (None,'gap')]
        for name,field,value,gap in tests:
            take,block=outcomes(rr,field,value,gap);s=stats(take);b=stats(block)
            lines.append(f"| {name} | {len(take)} | {sum(r['points']>0 for r in block)} | {sum(r['points']<0 for r in block)} | {s['net_points']:+.2f} | {-b['losing_points']:.2f} | {b['winning_points']:.2f} | {s['net_points']-baseline['net_points']:+.2f} |")
            decisions.extend(dict(period=label,rule=name,date=r['date'],signal=r['signal'],entry=r['entry'],exit=r['exit'],
                points=r['points'],decision='PASS' if r in take else 'BLOCK',field=field,value=r.get(field) if field else None,threshold=value,gap_min=gap) for r in rr)
        lines+=['','### Profitable bearish trades','',
            '| Date | Signal qualified | Entry–exit | Positive NIFTY points | Signal WMA | Strength | Gap | Expansion | Full WMA decline | Full RSI decline | Full EMA3 decline |',
            '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
        for r in rr:
            if r['points']<=0:continue
            lines.append('| '+' | '.join([r['date'],r['signal'][11:16],r['entry'][11:16]+'–'+r['exit'][11:16],f"{r['points']:+.2f}"]+
                [fmt(r[k]) for k in ('signal_wma','strength','gap','expansion','full_fall_wma','full_fall_rsi','full_fall_ema')])+' |')
    candle=['# Every candle: previous → signal → waiting → entry','',
        'RSI and EMA refer to RSI9 and EMA3 of RSI9. WMA is WMA21 of RSI9. '
        'Prior levels are reconstructed from the qualified signal and its recorded completed-5m changes; '
        'the prior candle’s own changes are unavailable here and are shown as dashes.','',
        '| Date | Trade entry | Candle available | Stage | RSI9 | EMA3 | WMA21 | ΔRSI | ΔEMA3 | ΔWMA | Bearish strength | Gap | Expansion |',
        '|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for s in steps:
        candle.append('| '+' | '.join([s['date'],s['entry'][11:16],s['time'][11:16],s['stage']]+
            [fmt(s.get(k)) for k in ('rsi','ema','wma','rsi_change','ema_change','wma_change','strength','gap','expansion')])+' |')
    detail=['# Filter decisions for every saved bearish trade','','Fixed-trade exclusions, not stateful replay results.','',
        '| Period | Rule | Date | Signal | Entry–exit | NIFTY points | Decision | Measured value | Threshold | Additional gap minimum |',
        '|---|---|---|---|---|---:|---|---|---|---|']
    for d in decisions:
        detail.append('| '+' | '.join(map(str,[d['period'],d['rule'],d['date'],d['signal'][11:16],d['entry'][11:16]+'–'+d['exit'][11:16],
            f"{d['points']:+.2f}",d['decision'],d['value'],d['threshold'],d['gap_min']]))+' |')
    output.mkdir(parents=True,exist_ok=True)
    for name,content in [('summary.md',lines),('candle-paths.md',candle),('filter-decisions.md',detail)]:
        (output/name).write_text('\n'.join(content)+'\n');print('REPORT:',output/name)
    (output/'report.json').write_text(json.dumps(dict(model='BEARISH_MOMENTUM_STAGED_SCREEN_V1',session_dates=days,
        provenance=proof,trades=rows,candles=steps,decisions=decisions,orders_sent=False),indent=2)+'\n')
    print('\n'.join(lines[:42]))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--test',action='store_true');p.add_argument('--root',action='append',type=Path)
    p.add_argument('--start-date',default='2026-07-19');p.add_argument('--end-date',default='2026-10-19')
    p.add_argument('--output',type=Path,default=Path('data/research/hilega-bearish-momentum-staged-20261019'))
    a=p.parse_args()
    if a.test:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    if not a.root:p.error('--root is required')
    rows=[];steps=[];proof={}
    for root in a.root:
        report=json.loads((root/'report.json').read_text())
        if report.get('model') not in bear.MODELS or report.get('status')!='COMPLETE':raise ValueError('COMPLETE_BULLISH_CONTROL_REQUIRED')
        for day in report['session_dates']:
            if not a.start_date<=day<=a.end_date:continue
            if day in proof:raise ValueError('DUPLICATE_SESSION:'+day)
            provenance=report['provenance'][day]
            if provenance.get('v20_control_parity')!='PASS':raise ValueError('CONTROL_PARITY_REQUIRED:'+day)
            session=json.loads((root/'sessions'/(day+'.json')).read_text())
            rules=session[bear.POLICY]['research_entry_rules']
            if rules.get('bullish_signal_gap_min')!=2 or rules.get('bullish_full_wma_min')!=2:
                raise ValueError('FIXED_BULLISH_2_2_REQUIRED:'+day)
            rr,ss=extract(day,session);rows.extend(rr);steps.extend(ss);proof[day]=provenance
    days=sorted(proof)
    if not days or days[-1]!=a.end_date:raise ValueError('END_SESSION_REQUIRED')
    write(a.output,days,rows,steps,proof)

class Checks(unittest.TestCase):
    def test_magnitude_includes_signal_change(self):
        sf=dict(rsi=50,ema=52,wma=55,rsi_change=-2,ema_change=-1,wma_change=-1,strength=-1)
        ef=dict(rsi=48,ema=50,wma=53,rsi_change=-2,ema_change=-2,wma_change=-2,strength=-2)
        m=momentum(sf,ef,[('signal',sf),('entry',ef)])
        self.assertEqual(m['full_fall_wma'],3);self.assertEqual(m['full_fall_rsi'],4)
        self.assertEqual(m['average_wma_decline'],1.5);self.assertEqual(m['entry_wma_acceleration'],1)
    def test_equality_numeric_allowed_but_acceleration_requires_positive(self):
        self.assertTrue(passed(dict(gap=2),'gap',2))
        self.assertFalse(passed(dict(entry_wma_acceleration=0),'entry_wma_acceleration','POSITIVE'))
    def test_unknown_rejected(self):
        with self.assertRaises(ValueError):passed({},'gap',2)
    def test_filters_account_for_winners_and_losers(self):
        rows=[dict(gap=1,points=50),dict(gap=1,points=-20),dict(gap=3,points=10)]
        take,block=outcomes(rows,'gap',2)
        self.assertEqual(stats(take)['net_points'],10)
        self.assertEqual(stats(block)['winning_points'],50);self.assertEqual(stats(block)['losing_points'],-20)

if __name__=='__main__':main()
