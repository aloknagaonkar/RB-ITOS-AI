"""Read-only bearish screening of saved bullish-2/2 stateful replays.

Fixed-trade screen, not a counterfactual stateful replay. No orders/live changes.
"""
import argparse
import json
import math
from pathlib import Path
import unittest
from hilega_bullish_month_gap_research import frame_index, features, stats

POLICY='BULLISH_GAP2_FULL_WMA2'
MODELS={'BULLISH_GAP2_FULL_WMA2_STATEFUL_V1','BULLISH_GAP_WMA_STATEFUL_SENSITIVITY_V1'}

def bearish_values(signal,entry):
    prior=signal['wma']-signal['wma_change']
    return dict(gap=-signal['gap'],strength=-signal['strength'],
                expansion=-signal['expansion'],prior_wma=prior,
                entry_wma=entry['wma'],magnitude=prior-entry['wma'])

def decision(row,gap,magnitude):
    if any(not isinstance(row.get(k),(int,float)) or not math.isfinite(row[k]) for k in ('gap','magnitude')):
        return 'UNKNOWN'
    return 'PASS' if row['gap']>=gap and row['magnitude']>=magnitude else 'BLOCK'

def extract(day,session):
    policy=session[POLICY];frames=frame_index(session['EXISTING']['audit']);out=[]
    for trade in policy['trades']:
        if trade['direction']!='BEARISH':continue
        entry=trade['entry_time']
        events=[e for e in policy.get('policy_events',[]) if e.get('event')=='FOLLOWUP_CANDLE_CHECK'
                and e.get('passed') is True and e.get('direction')=='BEARISH'
                and e.get('time')==entry and e.get('setup_available')==trade['signal_time']]
        signals={e.get('signal_time') for e in events}
        if len(signals)!=1 or None in signals:raise ValueError('EXACT_SIGNAL_IDENTITY_REQUIRED:'+entry)
        signal=signals.pop()
        if signal>=entry:raise ValueError('SIGNAL_MUST_PRECEDE_ENTRY:'+entry)
        sf=features(frames[signal]);ef=features(frames[entry])
        row=dict(date=day,setup=trade['signal_time'],signal=signal,entry=entry,
                 exit=trade['exit_time'],points=float(trade['points']),
                 signal_rsi=sf['rsi'],signal_ema=sf['ema'],signal_wma=sf['wma'],
                 entry_rsi=ef['rsi'],entry_ema=ef['ema'])
        row.update(bearish_values(sf,ef));out.append(row)
    return out

def table(lines,rows,gap,magnitude):
    groups={k:[r for r in rows if decision(r,gap,magnitude)==k] for k in ('PASS','BLOCK','UNKNOWN')}
    taken=stats(groups['PASS']);blocked=stats(groups['BLOCK'])
    lines.append(f"| {gap} | {magnitude} | {taken['trades']} | {blocked['trades']} | {len(groups['UNKNOWN'])} | {taken['net_points']:+.2f} | {-blocked['losing_points']:.2f} | {blocked['winning_points']:.2f} |")

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--test',action='store_true');p.add_argument('--root',type=Path,action='append')
    p.add_argument('--start-date',default='2026-07-19');p.add_argument('--end-date',default='2026-10-19')
    p.add_argument('--output',type=Path,default=Path('data/research/hilega-bearish-gap-magnitude-3months'))
    a=p.parse_args()
    if a.test:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    if not a.root:p.error('provide --root for each saved stateful replay batch')
    rows=[];days={};proof={}
    for root in a.root:
        report=json.loads((root/'report.json').read_text())
        if report.get('status')!='COMPLETE' or report.get('model') not in MODELS:
            raise ValueError('COMPLETE_STATEFUL_REPORT_REQUIRED:'+str(root))
        for day in report['session_dates']:
            if not a.start_date<=day<=a.end_date:continue
            if day in days:raise ValueError('DUPLICATE_SESSION:'+day)
            provenance=report['provenance'][day]
            if provenance.get('v20_control_parity')!='PASS':raise ValueError('CONTROL_PARITY_REQUIRED:'+day)
            session=json.loads((root/'sessions'/(day+'.json')).read_text())
            rules=session[POLICY].get('research_entry_rules',{})
            if rules.get('bullish_signal_gap_min')!=2 or rules.get('bullish_full_wma_min')!=2:
                raise ValueError('FIXED_BULLISH_2_2_REQUIRED:'+day)
            days[day]=True;proof[day]=provenance;rows.extend(extract(day,session))
    if not days or max(days)!=a.end_date:raise ValueError('END_SESSION_REQUIRED')
    lines=['# Bearish gap and WMA magnitude screening','',
        'Fixed bullish gap>=2 / full WMA magnitude>=2 replay is the source. Bearish trades alone are screened. '
        'This does not simulate changed positions or later candidates. Gross NIFTY points; costs excluded. '
        'Blocked winners/losers describe the saved trades, not executable counterfactual outcomes. No live changes.','',
        f'Coverage: {len(days)} saved sessions; {min(days)} through {max(days)}.','',
        '| Group | Trades | Winning points | Losing points | Net points |','|---|---:|---:|---:|---:|']
    for name,selected in [('ALL',rows),('WINNERS',[r for r in rows if r['points']>0]),('LOSERS',[r for r in rows if r['points']<0])]:
        s=stats(selected);lines.append(f"| {name} | {s['trades']} | {s['winning_points']:+.2f} | {s['losing_points']:.2f} | {s['net_points']:+.2f} |")
    for period in ['ALL']+sorted({d[:7] for d in days}):
        selected=rows if period=='ALL' else [r for r in rows if r['date'].startswith(period)]
        lines+=['',f'## Threshold screen — {period}','','| Signal gap minimum | Full downward WMA minimum | Passed | Blocked | Unknown | Passed net points | Loss points excluded | Winning points excluded |','|---:|---:|---:|---:|---:|---:|---:|---:|']
        for gap in (0,1,1.5,2,2.5,3):
            for magnitude in (0,1.8,2,2.2):table(lines,selected,gap,magnitude)
    lines+=['','## Every bearish trade','','| Date | Setup | Qualified signal | Entry–exit | NIFTY points | Signal RSI / EMA3 / WMA21 | Strength | Gap | Expansion | Prior WMA → entry WMA | Downward magnitude | Entry RSI / EMA3 |','|---|---|---|---|---:|---|---:|---:|---:|---|---:|---|']
    for r in sorted(rows,key=lambda r:r['entry']):
        lines.append(f"| {r['date']} | {r['setup'][11:16]} | {r['signal'][11:16]} | {r['entry'][11:16]}–{r['exit'][11:16]} | {r['points']:+.2f} | {r['signal_rsi']:.3f} / {r['signal_ema']:.3f} / {r['signal_wma']:.3f} | {r['strength']:.3f} | {r['gap']:.3f} | {r['expansion']:+.3f} | {r['prior_wma']:.3f} → {r['entry_wma']:.3f} | {r['magnitude']:.3f} | {r['entry_rsi']:.3f} / {r['entry_ema']:.3f} |")
    a.output.mkdir(parents=True,exist_ok=True)
    (a.output/'summary.md').write_text('\n'.join(lines)+'\n')
    (a.output/'report.json').write_text(json.dumps(dict(model='BEARISH_FIXED_BULLISH_2_2_SCREEN_V1',session_dates=sorted(days),provenance=proof,trades=rows,orders_sent=False),indent=2)+'\n')
    print('\n'.join(lines[:45]));print('FULL TABLE:',a.output/'summary.md')

class Checks(unittest.TestCase):
    def test_downward_sign_and_pre_signal_reference(self):
        v=bearish_values(dict(wma=50,wma_change=-1,gap=-3,strength=-1,expansion=-.5),dict(wma=48))
        self.assertEqual(v['magnitude'],3);self.assertEqual(v['gap'],3);self.assertEqual(v['expansion'],.5)
    def test_equality_passes(self):self.assertEqual(decision(dict(gap=2,magnitude=2),2,2),'PASS')
    def test_missing_is_unknown(self):self.assertEqual(decision(dict(gap=None,magnitude=2),2,2),'UNKNOWN')
    def test_recovered_loss_not_counted_as_profit(self):
        s=stats([dict(points=-20),dict(points=10)])
        self.assertEqual(s['losing_points'],-20);self.assertEqual(s['winning_points'],10)

if __name__=='__main__':main()
