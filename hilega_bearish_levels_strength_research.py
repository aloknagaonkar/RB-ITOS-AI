"""Bearish-only level, alignment and strength analysis of saved trades.

Fixed-trade exploratory screen, not a stateful replay. No trading operations.
Input is report.json produced by hilega_bearish_momentum_research.py.
"""
import argparse
from collections import defaultdict
from datetime import date
import json
import math
from pathlib import Path
import unittest

def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

def band(value):
    if not finite(value):raise ValueError('FINITE_INDICATOR_REQUIRED')
    if value<40:return 'LT40'
    if value<45:return '40_TO_LT45'
    if value<55:return '45_TO_LT55'
    if value<60:return '55_TO_LT60'
    return 'GE60'

def strength_band(value):
    if not finite(value):raise ValueError('FINITE_STRENGTH_REQUIRED')
    if value<.75:return 'LT0.75'
    if value<1:return '0.75_TO_LT1'
    if value<1.5:return '1_TO_LT1.5'
    return 'GE1.5'

def stats(rows):
    points=[r['points'] for r in rows]
    return dict(trades=len(rows),winners=sum(p>0 for p in points),losers=sum(p<0 for p in points),
        flat=sum(p==0 for p in points),winning=sum(max(0,p) for p in points),
        losing=-sum(min(0,p) for p in points),net=sum(points))

def normalize(row):
    r=dict(row)
    for k in ('signal_rsi','signal_ema','signal_wma','entry_rsi','entry_ema','entry_wma',
              'signal_strength','entry_strength','gap','expansion','points'):
        if not finite(r.get(k)):raise ValueError('MISSING_OR_NONFINITE:'+k+':'+str(r.get('entry')))
    for stage in ('signal','entry'):
        r[stage+'_alignment']=r[stage+'_rsi']<r[stage+'_ema']<r[stage+'_wma']
        for field in ('rsi','ema','wma'):r[stage+'_'+field+'_band']=band(r[stage+'_'+field])
        r[stage+'_strength_band']=strength_band(r[stage+'_strength'])
    return r

def rule_specs():
    specs=[('NO_EXTRA_FILTER',lambda r:True),('SIGNAL_BEARISH_ALIGNMENT',lambda r:r['signal_alignment'])]
    for field in ('rsi','ema','wma'):
        for threshold in (45,55,60):
            specs.append((f'SIGNAL_{field.upper()}_LT{threshold}',lambda r,f=field,t=threshold:r['signal_'+f]<t))
            specs.append((f'SIGNAL_{field.upper()}_GE{threshold}',lambda r,f=field,t=threshold:r['signal_'+f]>=t))
    for minimum in (1,1.5):
        specs.append((f'SIGNAL_STRENGTH_GE{minimum}',lambda r,m=minimum:r['signal_strength']>=m))
        for field in ('rsi','ema','wma'):
            for below in (True,False):
                label='LT55' if below else 'GE55'
                specs.append((f'SIGNAL_{field.upper()}_{label}_ALIGN_STRENGTH_GE{minimum}',
                    lambda r,f=field,b=below,m=minimum:r['signal_alignment'] and r['signal_strength']>=m and
                        ((r['signal_'+f]<55) if b else (r['signal_'+f]>=55))))
    return specs

def format_stats(s):
    return [str(s['trades']),str(s['winners']),str(s['losers']),str(s['flat']),
        f"{s['winning']:+.2f}",f"{-s['losing']:.2f}",f"{s['net']:+.2f}"]

def write(output,source):
    if source.get('model')!='BEARISH_MOMENTUM_STAGED_SCREEN_V1':raise ValueError('BEARISH_MOMENTUM_SOURCE_REQUIRED')
    days=sorted(source['session_dates'])
    if len(days)!=len(set(days)) or len(days)<30:raise ValueError('UNIQUE_30_PLUS_SESSIONS_REQUIRED')
    rows=[normalize(r) for r in source['trades']]
    seen=set()
    for r in rows:
        if r['date'] not in days:raise ValueError('TRADE_OUTSIDE_SESSION_COVERAGE')
        identity=(r['date'],r['entry'])
        if identity in seen:raise ValueError('DUPLICATE_TRADE:'+r['entry'])
        seen.add(identity)
    for day in days:
        date.fromisoformat(day)
        if source['provenance'][day].get('v20_control_parity')!='PASS':raise ValueError('CONTROL_PARITY_REQUIRED:'+day)
    lines=['# Bearish indicator levels, alignment and strength','',
        'Bearish trades only, from the saved EMA10-touch replay with bullish 2/2 fixed and no extra bearish filter. '
        'Fixed-trade research: no changed-state replay, costs or option fills. No live changes. '
        'Signal and entry values remain separate. EMA3/WMA21 are of RSI9, not NIFTY price averages. '
        'Bands include their lower boundary and exclude their upper boundary; 55 belongs to 55–<60. '
        'Strength is positive directional WMA decline. Small groups are descriptive, not validated filters.','']
    decisions=[]
    for label,selected in [('LAST_10',days[-10:]),('LAST_30',days[-30:]),('FULL_SAVED_PERIOD',days)]:
        rr=[r for r in rows if r['date'] in selected];baseline=stats(rr)
        lines += [f'## {label}: {selected[0]} through {selected[-1]}','',
            f"Sessions {len(selected)}; trades {len(rr)}; net {baseline['net']:+.2f} NIFTY points.",'']
        for stage in ('signal','entry'):
            lines += [f'### {stage.upper()} values — independent groups','',
                '| Indicator | Band | Trades | Winners | Losers | Flat | Winning points | Losing points | Net points |',
                '|---|---|---:|---:|---:|---:|---:|---:|---:|']
            for field in ('rsi','ema','wma','strength'):
                groups=defaultdict(list)
                for r in rr:groups[r[stage+'_'+field+'_band']].append(r)
                for group,items in sorted(groups.items()):
                    lines.append('| '+' | '.join([field.upper(),group]+format_stats(stats(items)))+' |')
        lines += ['','### Signal alignment × WMA level × strength','',
            '| Bearish alignment | Signal WMA band | Signal strength band | Trades | Winners | Losers | Flat | Winning points | Losing points | Net points |',
            '|---|---|---|---:|---:|---:|---:|---:|---:|---:|']
        groups=defaultdict(list)
        for r in rr:groups[(r['signal_alignment'],r['signal_wma_band'],r['signal_strength_band'])].append(r)
        for group,items in sorted(groups.items()):
            lines.append('| '+' | '.join([str(v) for v in group]+format_stats(stats(items)))+' |')
        lines += ['','### Joint RSI / EMA / WMA levels at signal','',
            '| RSI band | EMA3 band | WMA21 band | Trades | Winners | Losers | Flat | Winning points | Losing points | Net points |',
            '|---|---|---|---:|---:|---:|---:|---:|---:|---:|']
        groups=defaultdict(list)
        for r in rr:groups[(r['signal_rsi_band'],r['signal_ema_band'],r['signal_wma_band'])].append(r)
        for group,items in sorted(groups.items()):lines.append('| '+' | '.join(list(group)+format_stats(stats(items)))+' |')
        lines += ['','### Prespecified level and strength screens','',
            '| Rule | Passed | Blocked winners | Blocked losers | Passed net | Loss points excluded | Winning points excluded | Net change |',
            '|---|---:|---:|---:|---:|---:|---:|---:|']
        for name,condition in rule_specs():
            take=[r for r in rr if condition(r)];block=[r for r in rr if not condition(r)]
            s=stats(take);b=stats(block)
            lines.append(f"| {name} | {s['trades']} | {b['winners']} | {b['losers']} | {s['net']:+.2f} | {b['losing']:.2f} | {b['winning']:.2f} | {s['net']-baseline['net']:+.2f} |")
            for r in rr:decisions.append(dict(period=label,rule=name,date=r['date'],setup=r['setup'],signal=r['signal'],
                entry=r['entry'],exit=r['exit'],points=r['points'],passed=condition(r)))
    detail=['# Every bearish trade: signal and entry values','',
        '| Date | Setup | Signal qualified | Entry–exit | NIFTY points | Outcome | Signal RSI / EMA / WMA | Signal alignment | Signal strength | Signal gap | Signal expansion | Entry RSI / EMA / WMA | Entry alignment | Entry strength | Full WMA decline |',
        '|---|---|---|---|---:|---|---|---|---:|---:|---:|---|---|---:|---:|']
    for r in sorted(rows,key=lambda x:x['entry']):
        value=lambda k:f"{r[k]:.3f}"
        alignment=lambda stage:'PASS' if r[stage+'_alignment'] else 'FAIL'
        detail.append('| '+' | '.join([r['date'],r['setup'][11:16],r['signal'][11:16],r['entry'][11:16]+'–'+r['exit'][11:16],
            f"{r['points']:+.2f}",'WIN' if r['points']>0 else 'LOSS' if r['points']<0 else 'FLAT',
            ' / '.join(value('signal_'+k) for k in ('rsi','ema','wma')),alignment('signal'),value('signal_strength'),value('gap'),value('expansion'),
            ' / '.join(value('entry_'+k) for k in ('rsi','ema','wma')),alignment('entry'),value('entry_strength'),value('full_fall_wma')])+' |')
    paths=['# Previous candle through entry — bearish only','',
        'Prior levels are reconstructed from signal values and recorded completed-five-minute changes. Prior candle changes are unavailable.','',
        '| Date | Trade entry | Candle available | Stage | RSI9 | EMA3 of RSI | WMA21 of RSI | Alignment | ΔRSI | ΔEMA | ΔWMA | Strength | Gap | Expansion |',
        '|---|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|']
    for c in source['candles']:
        fmt=lambda k:'—' if c.get(k) is None else f"{c[k]:.3f}"
        paths.append('| '+' | '.join([c['date'],c['entry'][11:16],c['time'][11:16],c['stage'],fmt('rsi'),fmt('ema'),fmt('wma'),
            'PASS' if c['rsi']<c['ema']<c['wma'] else 'FAIL']+[fmt(k) for k in ('rsi_change','ema_change','wma_change','strength','gap','expansion')])+' |')
    screens=['# Per-trade screen decisions','','Fixed-trade PASS/BLOCK; no counterfactual entry is simulated.','',
        '| Period | Rule | Date | Qualified signal | Entry–exit | NIFTY points | Decision |','|---|---|---|---|---|---:|---|']
    for d in decisions:screens.append('| '+' | '.join([d['period'],d['rule'],d['date'],d['signal'][11:16],d['entry'][11:16]+'–'+d['exit'][11:16],f"{d['points']:+.2f}",'PASS' if d['passed'] else 'BLOCK'])+' |')
    output.mkdir(parents=True,exist_ok=True)
    for filename,content in [('summary.md',lines),('trade-values.md',detail),('candle-paths.md',paths),('filter-decisions.md',screens)]:
        (output/filename).write_text('\n'.join(content)+'\n');print('REPORT:',output/filename)
    (output/'report.json').write_text(json.dumps(dict(model='BEARISH_LEVEL_ALIGNMENT_STRENGTH_V1',session_dates=days,
        provenance=source['provenance'],trades=rows,decisions=decisions,orders_sent=False),indent=2)+'\n')
    print('\n'.join(lines[:35]))

class Checks(unittest.TestCase):
    def test_exclusive_band_boundaries(self):
        self.assertEqual([band(v) for v in (39.99,40,45,55,60)],['LT40','40_TO_LT45','45_TO_LT55','55_TO_LT60','GE60'])
    def test_missing_and_nonfinite_rejected(self):
        for v in (None,float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):band(v)
    def test_strength_boundaries(self):
        self.assertEqual(strength_band(.75),'0.75_TO_LT1');self.assertEqual(strength_band(1.5),'GE1.5')
    def test_positive_negative_flat_counted(self):
        s=stats([dict(points=20),dict(points=-5),dict(points=0)])
        self.assertEqual((s['winners'],s['losers'],s['flat'],s['net']),(1,1,1,15))
    def test_threshold_complement_and_combination(self):
        rules=dict(rule_specs());r=dict(signal_rsi=55,signal_ema=54,signal_wma=60,signal_alignment=False,signal_strength=2)
        self.assertFalse(rules['SIGNAL_RSI_LT55'](r));self.assertTrue(rules['SIGNAL_RSI_GE55'](r))
        self.assertFalse(rules['SIGNAL_WMA_GE55_ALIGN_STRENGTH_GE1'](r))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--test',action='store_true')
    p.add_argument('--input',type=Path,default=Path('data/research/hilega-bearish-momentum-staged-20261019/report.json'))
    p.add_argument('--output',type=Path,default=Path('data/research/hilega-bearish-levels-strength-20261019'))
    a=p.parse_args()
    if a.test:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    write(a.output,json.loads(a.input.read_text()))

if __name__=='__main__':main()
