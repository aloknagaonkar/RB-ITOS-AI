"""Individual bullish gap and magnitude ablation on V20, research only.

Same CLI as hilega_bullish_gap_magnitude_stateful.py; no live changes/orders.
"""
import sys
import unittest
from hilega_bullish_month_gap_research import frame_index, features
import hilega_bullish_gap_magnitude_stateful as base

SPECS=[('BULLISH_GAP2',2,0),('BULLISH_FULL_WMA2_ONLY',0,2),('BULLISH_GAP2_FULL_WMA2',2,2)]
ORIGINAL_COMPACT=base.compact

def cell(trades):
    return '<br>'.join(f"{t['entry_time'][11:16]}–{t['exit_time'][11:16]} · {t['points']:+.2f}" for t in trades) or '—'

def compact(output,results,stats):
    ORIGINAL_COMPACT(output,results,stats)
    keys=('EXISTING','FRESH_AND','FRESH_AND_EMA10_ENTRY','EXISTING_BASELINE_2')+tuple(name for name,_,_ in SPECS)
    lines=['# Signal-wise individual bullish filter comparison','',
        'Research replay. Gross NIFTY points before costs. Original live-strategy reconstruction is contextual; '
        'compare each individual addition against FRESH_AND_EMA10_ENTRY to isolate its effect. '
        'Bearish entry rules and exits remain unchanged, although changed positions can affect later trades. '
        'A dash means no executed trade from that exact setup, not proof of a direct veto.','',
        '| Date | Direction | Setup available | Existing strategy | Fresh AND baseline | Latest: EMA10-touch wait | Existing baseline 2 | Bullish gap ≥2 only | Bullish magnitude ≥2 only | Current tested: bullish gap ≥2 + magnitude ≥2 |',
        '|---|---|---|---|---|---|---|---|---|---|']
    changed=[]
    for day,variants in sorted(results.items()):
        ids={(t['direction'],t['signal_time']) for key in keys for t in variants[key]['trades']}
        for side,setup in sorted(ids,key=lambda x:(x[1],x[0])):
            groups=[[t for t in variants[key]['trades'] if t['direction']==side and t['signal_time']==setup] for key in keys]
            lines.append('| '+' | '.join([day,side,setup[11:16]]+[cell(g) for g in groups])+' |')
            control=groups[2]
            for key,group in zip(keys[4:],groups[4:]):
                if stats.signature(control)==stats.signature(group):continue
                before=sum(t['points'] for t in control);after=sum(t['points'] for t in group)
                reason='NOT_TAKEN_FROM_THIS_SETUP' if control and not group else 'NEW_ENTRY_FROM_THIS_SETUP' if group and not control else 'ENTRY_OR_EXIT_CHANGED'
                changed.append([day,side,setup[11:16],key,cell(control),cell(group),f'{after-before:+.2f}',reason])
    (output/'daily-signal-comparison.md').write_text('\n'.join(lines)+'\n')
    changes=['# Changed winning and losing trade outcomes','',
        'Setup-level attribution. Changes may be delayed entries or later state effects; explicit filter failures are separate evidence.','',
        '| Date | Direction | Setup | Policy | EMA10-touch control | Tested trade | Point change | Classification |',
        '|---|---|---|---|---|---|---:|---|']
    changes += ['| '+' | '.join(row)+' |' for row in changed]
    (output/'changed-trades.md').write_text('\n'.join(changes)+'\n')
    outcomes=['# All winning, losing and flat trades','',
        '| Date | Policy | Direction | Setup | Entry–exit | NIFTY points | Outcome |',
        '|---|---|---|---|---|---:|---|']
    for day,variants in sorted(results.items()):
        for key in keys:
            for t in variants[key]['trades']:
                outcome='WIN' if t['points']>0 else 'LOSS' if t['points']<0 else 'FLAT'
                outcomes.append('| '+' | '.join([day,key,t['direction'],t['signal_time'][11:16],
                    t['entry_time'][11:16]+'–'+t['exit_time'][11:16],f"{t['points']:+.2f}",outcome])+' |')
    (output/'all-trade-outcomes.md').write_text('\n'.join(outcomes)+'\n')
    values=['# Completed five-minute values for manual validation','',
        'Values at entry are from the latest completed five-minute frame available by entry. '
        'For original minute-entry strategies, these are five-minute context, not their minute confirmation values. '
        'Qualified signal time is shown only when an exact successful follow-up event identifies it. '
        'Strength/gap/expansion use the trade direction; EMA3 is EMA3 of RSI9, not price EMA10.','',
        '| Date | Policy | Direction | Setup | Qualified signal | Entry–exit | NIFTY points | Completed frame at entry | RSI9 | EMA3 of RSI | WMA21 of RSI | Directional strength | Gap | Expansion |',
        '|---|---|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|']
    for day,variants in sorted(results.items()):
        frames=frame_index(variants['EXISTING']['audit'])
        for key in keys:
            for t in variants[key]['trades']:
                times=[at for at in frames if at<=t['entry_time']]
                if not times:raise ValueError('COMPLETED_ENTRY_CONTEXT_REQUIRED:'+t['entry_time'])
                at=max(times);f=features(frames[at]);direction=1 if t['direction']=='BULLISH' else -1
                signals={e.get('signal_time') for e in variants[key].get('policy_events',[])
                    if e.get('event')=='FOLLOWUP_CANDLE_CHECK' and e.get('passed') is True
                    and e.get('direction')==t['direction'] and e.get('time')==t['entry_time']
                    and e.get('setup_available')==t['signal_time']}
                signal=next(iter(signals)) if len(signals)==1 else None
                values.append('| '+' | '.join([day,key,t['direction'],t['signal_time'][11:16],signal[11:16] if signal else '—',
                    t['entry_time'][11:16]+'–'+t['exit_time'][11:16],f"{t['points']:+.2f}",at[11:16]]+
                    [f"{v:.3f}" for v in (f['rsi'],f['ema'],f['wma'],direction*f['strength'],direction*f['gap'],direction*f['expansion'])])+' |')
    (output/'signal-validation-values.md').write_text('\n'.join(values)+'\n')
    for name in ('daily-signal-comparison.md','changed-trades.md','all-trade-outcomes.md','signal-validation-values.md'):
        print('TRADE REPORT:',output/name)

class Checks(unittest.TestCase):
    def test_additions_are_separate(self):
        self.assertEqual([(g,m) for _,g,m in SPECS],[(2,0),(0,2),(2,2)])
    def test_zero_gap_does_not_veto_qualified_positive_gap(self):
        e=dict(passed=True,reasons=[])
        base.apply_gap(e,dict(ema3_rsi=50.1,wma21_rsi=50),0)
        self.assertTrue(e['passed'])

def main():
    if '--sensitivity' in sys.argv:raise ValueError('USE_INDIVIDUAL_COMPARISON_NOT_SENSITIVITY')
    if '--test' in sys.argv:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
        if not result.wasSuccessful():raise SystemExit(1)
    base.MODEL='BULLISH_INDIVIDUAL_GAP_MAGNITUDE_V1'
    base.SPECS=SPECS
    base.EXTRAS=tuple(name for name,_,_ in SPECS)
    base.RULE_TEXT=('Three separate bullish additions to unchanged V20 EMA10-touch control: signal gap>=2 only, '
        'full pre-signal-to-entry WMA rise>=2 only, and both together. '
        'For bullish magnitude, use entry WMA minus WMA immediately BEFORE the qualified signal; '
        'this is indicator points, not NIFTY price points. '
        'Signal gap is EMA3(RSI9)-WMA21(RSI9) and also gates opposite-watch qualification. '
        'Magnitude checks an otherwise valid entry; failed magnitude follows original EMA10-touch retention/fresh-signal lifecycle. '
        'Bearish rules, existing exits, follow-up checks and cutoff retained. Stateful research; gross NIFTY points, costs excluded. '
        'Previously examined sample; no independent holdout or live changes.')
    base.compact=compact
    base.main()

if __name__=='__main__':main()
