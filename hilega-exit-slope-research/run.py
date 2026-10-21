"""Offline directional WMA exit-slope study over deployed WMA40/reversal control."""
import argparse
from datetime import datetime
import importlib.util
import json
import math
from pathlib import Path
import types
from control_cache import fingerprint,load_or_validate
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('slope_core',HERE/'timing_core.py')
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
base=core.policy5
EXPECTED='bullish-gap2-full-wma2-2.0.0-wma40-reversal'

def slope_check(side,current,reference):
    values=[getattr(current,'wma21_rsi',None),getattr(reference,'wma21_rsi',None)]
    valid=bool(getattr(current,'ready',False) and getattr(reference,'ready',False) and all(v is not None and not isinstance(v,bool) and math.isfinite(float(v)) for v in values))
    delta=float(values[0])-float(values[1]) if valid else None
    return dict(previous_wma=values[1],current_wma=values[0],delta_wma=delta,
        slope_pass=bool(valid and (delta<0 if side=='BULLISH' else delta>0)),
        slope_rule='FALLING' if side=='BULLISH' else 'RISING')

def study_policy(sides):
    if base.VERSION!=EXPECTED:raise ValueError('DEPLOYED_CONTROL_VERSION_MISMATCH')
    p=types.ModuleType('market_lab._offline_exit_slope');p.__package__='market_lab';p.__file__=base.__file__
    exec(compile(Path(base.__file__).read_text(),base.__file__,'exec'),p.__dict__)
    standard=p._advance_standard
    def boundary(c,g,bar,reference,tracker,manual_block=False):
        before=g.owner
        original=p.dual_exit
        def checked(side,current):
            return original(side,current) and (side not in sides or slope_check(side,current,reference)['slope_pass'])
        p.dual_exit=checked
        try:result=standard(c,g,bar,reference,tracker,manual_block)
        finally:p.dual_exit=original
        if before in ('BULLISH','BEARISH'):
            current=result['current'];ev=result['exit_validation']
            evidence=slope_check(before,current,reference)
            ev.update(evidence,slope_required=before in sides,original_dual_exit=original(before,current))
            # Keep original dual predicate distinct from final slope-gated permission.
            ev['dual_exit_pass']=ev['original_dual_exit']
            if before in sides and ev['original_dual_exit'] and not evidence['slope_pass']:
                ev['action']='HOLD_EXIT_SLOPE_NOT_MET'
        return result
    p._advance_standard=boundary
    return p

def signature(trades):
    return sorted((t['direction'],t['entry_time'],t['exit_time'],round(t['entry_price'],5),round(t['exit_price'],5),round(t['points'],5),t['exit_reason']) for t in trades)

def stats(trades):
    equity=peak=dd=0
    for t in sorted(trades,key=lambda t:t['exit_time']):
        equity+=t['points'];peak=max(peak,equity);dd=max(dd,peak-equity)
    return dict(trades=len(trades),winning_points=sum(max(t['points'],0) for t in trades),losing_points=sum(min(t['points'],0) for t in trades),net_points=equity,drawdown=dd)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input-zip',type=Path,required=True)
    ap.add_argument('--date',default='2026-10-21')
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--force-control-parity',action='store_true')
    args=ap.parse_args()
    if base.VERSION!=EXPECTED:raise ValueError('DEPLOYED_CONTROL_VERSION_MISMATCH')
    from market_lab import hilega_combined_replay_v1 as replay
    warm,_=core.read_inputs(args.input_zip);day=args.date;raw=dict(warm)[day]
    until=datetime.fromisoformat(day+'T14:55:00+05:30')
    sources=list(Path(base.__file__).parent.rglob('*.py'))+[Path(__file__),HERE/'timing_core.py',HERE/'control_cache.py']
    def validate(control):
        r=replay.replay(day,raw,[(d,v) for d,v in warm if d<day])
        if signature(control['trades'])!=signature(r['trades']):raise ValueError('BASELINE_PARITY_FAILED')
    control,basis=load_or_validate(Path('data/research/hilega-exit-slope-control-cache-v1'),fingerprint(day,raw,warm,sources,base.VERSION),lambda:core.run(base,core.legacy5,warm,raw,day,5,until),validate,force=args.force_control_parity)
    policies={'CURRENT_DEPLOYED':control}
    for name,sides in [('BULLISH_FALLING_WMA',{'BULLISH'}),('BEARISH_RISING_WMA',{'BEARISH'}),('BOTH_EXIT_SLOPES',{'BULLISH','BEARISH'})]:
        policies[name]=core.run(study_policy(sides),core.legacy5,warm,raw,day,5,until)
    if any(r['open_trade'] for r in policies.values()):raise ValueError('UNRESOLVED_POSITION')
    lines=['# Exit WMA slope — '+day,'','Research only; gross NIFTY points; no option fills/costs.',
        'Deployed entries and bearish WMA40+confirmed bullish reversal retained. Reversal/cutoff bypass new normal-exit slope gate.',
        'Delta = exit-candle WMA minus preceding completed5m WMA; bullish requires negative; bearish positive. Equality holds.','',
        '| Policy | Trades | Winning points | Losing points | Net points | Change | Drawdown |','|---|---:|---:|---:|---:|---:|---:|']
    control_points=stats(control['trades'])['net_points']
    for name,r in policies.items():
        st=stats(r['trades']);r['stats']=st
        lines.append(f"| {name} | {st['trades']} | {st['winning_points']:+.2f} | {st['losing_points']:+.2f} | {st['net_points']:+.2f} | {st['net_points']-control_points:+.2f} | {st['drawdown']:.2f} |")
    lines+=['','| Policy | Direction | Setup | Qualified | Entry–exit | NIFTY points | Exit reason |','|---|---|---|---|---|---:|---|']
    hm=lambda t:t[11:16] if t else '—'
    checks=['# Exit evidence — '+day,'','| Policy | Time | Direction | RSI9 | EMA3 RSI | Previous WMA | Current WMA | Delta | Original dual exit | Slope required | Slope pass | Action |','|---|---|---|---:|---:|---:|---:|---:|---|---|---|---|']
    for name,r in policies.items():
        for t in r['trades']:
            lines.append(f"| {name} | {t['direction']} | {hm(t.get('setup'))} | {hm(t.get('qualified'))} | {hm(t['entry_time'])}–{hm(t['exit_time'])} | {t['points']:+.2f} | {t['exit_reason']} |")
        for a in r['audit']:
            ev=a.get('exit_validation') or {}
            if not ev:continue
            f=a.get('frame') or {};previous=ev.get('previous_wma',f.get('previous_wma21_rsi'))
            current=ev.get('current_wma',ev.get('wma21'))
            delta=ev.get('delta_wma',current-previous if current is not None and previous is not None else None)
            checks.append(f"| {name} | {hm(a['time'])} | {ev.get('direction')} | {ev.get('rsi9')} | {ev.get('ema3')} | {previous} | {current} | {delta} | {ev.get('original_dual_exit',ev.get('dual_exit_pass'))} | {ev.get('slope_required',False)} | {ev.get('slope_pass','—')} | {ev.get('action')} |")
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'report.json').write_text(json.dumps(dict(status='COMPLETE',session_date=day,baseline_parity='PASS',parity_basis=basis,policies=policies,orders_sent=False),indent=2))
    (args.output/'comparison.md').write_text('\n'.join(lines)+'\n')
    (args.output/'exit-validation.md').write_text('\n'.join(checks)+'\n')
    print('Baseline parity: PASS ('+basis+')');print('\n'.join(lines));print('REPORT:',args.output/'report.json')

if __name__=='__main__':main()
