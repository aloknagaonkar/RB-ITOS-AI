"""Offline no-touch signal entry. Never installs or changes live strategy modules."""
import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import types
from control_cache import fingerprint,load_or_validate

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('no_touch_core',HERE/'timing_core.py')
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
base=core.policy5
EXPECTED='bullish-gap2-full-wma2-2.0.0-wma40-reversal'

def no_touch_check(side,evidence,at,minimum=2):
    """Called only after ordinary fresh-signal checks, never for a follow-up."""
    reasons=[]
    vals=[evidence.get(k) for k in ('low','high','ema10')]
    valid=all(v is not None and not isinstance(v,bool) and math.isfinite(float(v)) for v in vals)
    valid=valid and evidence.get('available_at')==at.isoformat()
    clear=bool(valid and (float(vals[0])>float(vals[2]) if side=='BULLISH' else float(vals[1])<float(vals[2])))
    if not evidence.get('passed'):reasons.append('SIGNAL_REQUIREMENTS_FAILED')
    if not clear:reasons.append('EMA10_TOUCH_OR_NOT_CLEAR_OR_MISSING')
    magnitude=None
    if side=='BULLISH':
        w=evidence.get('wma21_rsi');p=evidence.get('previous_wma21_rsi')
        if all(v is not None and not isinstance(v,bool) and math.isfinite(float(v)) for v in (w,p)):
            magnitude=float(w)-float(p)
        if magnitude is None or magnitude<minimum:reasons.append('BULLISH_FULL_WMA_MAGNITUDE_BELOW_MIN_OR_MISSING')
    if at.strftime('%H:%M')>='14:55':reasons.append('SESSION_CUTOFF')
    return dict(passed=not reasons,reasons=reasons,entire_candle_clear=clear,
        clearance_points=(float(vals[0])-float(vals[2]) if side=='BULLISH' else float(vals[2])-float(vals[1])) if valid else None,
        full_wma_magnitude=magnitude,full_wma_min=minimum if side=='BULLISH' else None,
        ema_comparison_basis='COMPLETED_SIGNAL_CANDLE_EMA10')

def replace_once(source,old,new):
    if source.count(old)!=1:raise ValueError('RESEARCH_SOURCE_ANCHOR_MISMATCH:'+old[:70])
    return source.replace(old,new)

def study_policy(enabled=True):
    if base.VERSION!=EXPECTED:raise ValueError('DEPLOYED_CONTROL_VERSION_MISMATCH')
    source=Path(base.__file__).read_text()
    anchor="                if followup and evidence['passed']:\n                    self.followup_signal="
    replacement="""                bypass=no_touch_check(side,evidence,at,full_wma_min) if followup and evidence['passed'] else None
                if bypass is not None:
                    evidence['no_touch_entry']=bypass
                    if bypass['passed']:
                        evidence.update(entry_confirmation_route='SIGNAL_NO_EMA10_TOUCH',signal_time=at.isoformat(),followup_required=False)
                        if side=='BULLISH':apply_magnitude(evidence,dict(time=at),frames,at,full_wma_min)
                if followup and evidence['passed'] and not (bypass and bypass['passed']):
                    self.followup_signal="""
    if enabled:
        source=replace_once(source,anchor,replacement)
        source=replace_once(source,"v.get('event')=='FOLLOWUP_CANDLE_CHECK' and v.get('direction')==direction(e)","v.get('event') in ('FOLLOWUP_CANDLE_CHECK','EMA10_ENTRY_CHECK') and v.get('direction')==direction(e)")
    policy=types.ModuleType('market_lab._research_no_touch')
    policy.__package__='market_lab';policy.__file__=base.__file__
    policy.__dict__['no_touch_check']=no_touch_check
    exec(compile(source,base.__file__,'exec'),policy.__dict__)
    # Reversal monitor always uses the deployed full follow-up gate.
    policy._start_bullish_exit_monitor=base._start_bullish_exit_monitor
    return policy

def signature(trades):
    return sorted((t['direction'],t['entry_time'],t['exit_time'],round(t['entry_price'],5),round(t['exit_price'],5),round(t['points'],5),t['exit_reason']) for t in trades)

def stats(trades):
    equity=peak=dd=0
    for t in sorted(trades,key=lambda t:t['exit_time']):
        equity+=t['points'];peak=max(peak,equity);dd=max(dd,peak-equity)
    return dict(trades=len(trades),winners=sum(t['points']>0 for t in trades),losers=sum(t['points']<0 for t in trades),
        winning_points=sum(max(t['points'],0) for t in trades),losing_points=sum(min(t['points'],0) for t in trades),net_points=equity,drawdown=dd)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input-zip',type=Path,required=True)
    ap.add_argument('--date',action='append')
    ap.add_argument('--month',default='2026-10')
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--control-cache',type=Path,default=Path('data/research/hilega-no-touch-control-cache-v1'))
    ap.add_argument('--force-control-parity',action='store_true')
    args=ap.parse_args()
    if base.VERSION!=EXPECTED:raise ValueError('DEPLOYED_CONTROL_VERSION_MISMATCH')
    from market_lab import hilega_combined_replay_v1 as replay
    warm,_=core.read_inputs(args.input_zip);raws=dict(warm)
    days=sorted(set(args.date or [d for d,_ in warm if d.startswith(args.month+'-')]))
    if not days:raise ValueError('NO_SAVED_SESSIONS')
    policy=study_policy();sources=list(Path(base.__file__).parent.rglob('*.py'))+[Path(__file__),HERE/'timing_core.py',HERE/'control_cache.py']
    args.output.mkdir(parents=True,exist_ok=True)
    results=[];checks=['# Entry decision audit','', '| Date | Time IST | Direction | Strength | Gap | Expansion | Entry decision | EMA10 / no-touch evidence |','|---|---|---|---:|---:|---:|---|---|']
    details=['# Signal-wise comparison','', 'Gross NIFTY points; no option fills/costs. Research only. Same deployed exits and full reversal confirmation.',
        'Setup available and signal qualification are different stages. A dash means no trade from that setup; it does not prove a direct veto.','']
    for day in days:
        try:
            raw=raws[day];until=datetime.fromisoformat(day+'T14:55:00+05:30')
            def validate(b):
                other=replay.replay(day,raw,[(d,r) for d,r in warm if d<day])
                if signature(b['trades'])!=signature(other['trades']):raise ValueError('BASELINE_PARITY_FAILED')
            control,basis=load_or_validate(args.control_cache,fingerprint(day,raw,warm,sources,base.VERSION),
                lambda:core.run(base,core.legacy5,warm,raw,day,5,until),validate,force=args.force_control_parity)
            variant=core.run(policy,core.legacy5,warm,raw,day,5,until)
            if control['open_trade'] or variant['open_trade']:raise ValueError('UNRESOLVED_POSITION')
            policies={'CURRENT_DEPLOYED':control,'NO_TOUCH_SIGNAL_ENTRY':variant}
            for value in policies.values():value['stats']=stats(value['trades'])
            row=dict(session_date=day,status='COMPLETE',baseline_parity='PASS',parity_basis=basis,policies=policies)
            details+=['## '+day,'','| Direction | Setup available | Current: signal / entry–exit · points | No-touch: signal / entry–exit · points | Tested entry route |','|---|---|---|---|---|']
            identities=sorted({(t['direction'],t['setup']) for v in policies.values() for t in v['trades']},key=lambda x:(x[1],x[0]))
            hm=lambda t:t[11:16] if t else '—'
            def cell(t):return f"{hm(t.get('qualified'))} / {hm(t['entry_time'])}–{hm(t['exit_time'])} · {t['points']:+.2f}" if t else '—'
            for side,setup in identities:
                lists=[[t for t in v['trades'] if (t['direction'],t['setup'])==(side,setup)] for v in policies.values()]
                a,b=lists
                route='; '.join((t.get('entry_evidence') or {}).get('entry_confirmation_route','FOLLOWUP_OR_EXISTING') for t in b) or '—'
                details.append(f"| {side} | {hm(setup)} | {'; '.join(map(cell,a)) or '—'} | {'; '.join(map(cell,b)) or '—'} | {route} |")
            for audit in variant['audit']:
                for check in audit['checks']:
                    ev=check.get('ema10_entry') or {}
                    if not ev:continue
                    checks.append(f"| {day} | {hm(audit['time'])} | {check['direction']} | {check.get('directional_wma_strength')} | {check.get('current_gap')} | {check.get('gap_delta')} | {check['status']} | {json.dumps(ev,sort_keys=True)} |")
        except Exception as exc:row=dict(session_date=day,status='INCOMPLETE',issues=[type(exc).__name__+': '+str(exc)])
        results.append(row);(args.output/(day+'.json')).write_text(json.dumps(row,indent=2))
        print(json.dumps({k:v for k,v in row.items() if k!='policies'}),flush=True)
    complete=[r for r in results if r['status']=='COMPLETE']
    lines=['# No-touch entry comparison','',f'Coverage: {len(complete)}/{len(days)} saved sessions','',
        '| Policy | Trades | Winning points | Losing points | Net points | Winners | Losers | Drawdown |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name in ('CURRENT_DEPLOYED','NO_TOUCH_SIGNAL_ENTRY'):
        st=stats([t for r in complete for t in r['policies'][name]['trades']])
        lines.append(f"| {name} | {st['trades']} | {st['winning_points']:+.2f} | {st['losing_points']:+.2f} | {st['net_points']:+.2f} | {st['winners']} | {st['losers']} | {st['drawdown']:.2f} |")
    lines+=['','| Date | Current points | No-touch points | Change |','|---|---:|---:|---:|']
    for r in complete:
        a,b=[v['stats']['net_points'] for v in r['policies'].values()]
        lines.append(f"| {r['session_date']} | {a:+.2f} | {b:+.2f} | {b-a:+.2f} |")
    report=dict(status='COMPLETE' if len(complete)==len(days) else 'INCOMPLETE',sessions=results,orders_sent=False,observation_only=True)
    for name,content in [('summary.md',lines),('signal-comparison.md',details),('entry-validation.md',checks)]:
        (args.output/name).write_text('\n'.join(content)+'\n')
    (args.output/'report.json').write_text(json.dumps(report,indent=2))
    print('\n'.join(lines));print('REPORT:',args.output/'report.json')

if __name__=='__main__':main()
