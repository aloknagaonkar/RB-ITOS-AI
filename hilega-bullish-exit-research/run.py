"""October bullish WMA60 research over the deployed WMA40 reversal control."""
import argparse
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import types

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('exit_timing_core',HERE/'timing_core.py')
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
base=core.policy5
legacy=core.legacy5

def normal_exit_allowed(side,current):
    dual=base.dual_exit(side,current)
    return dual and (side!='BULLISH' or current.wma21_rsi<60)

def signature(trades):
    return sorted((t['direction'],t['entry_time'],t['exit_time'],round(t['entry_price'],5),
        round(t['exit_price'],5),round(t['points'],5)) for t in trades)

class Study:
    def __init__(self,reversal):
        # A private module namespace keeps even the exit override off live modules.
        self.policy=types.ModuleType('market_lab._offline_bearish_exit')
        self.policy.__package__='market_lab'
        self.policy.__file__=base.__file__
        exec(compile(Path(base.__file__).read_text(),base.__file__,'exec'),self.policy.__dict__)
        self.policy.dual_exit=normal_exit_allowed
        self.advance=self.policy.advance_boundary
        self.policy.advance_boundary=self.boundary
        self.reversal=reversal
        self.monitor=None
        self.exit_audit=[]
        self.opposite_audit=[]

    def start_monitor(self,c,tracker):
        m=deepcopy(c)
        day=c.session_date
        m.bullish.session=legacy.SessionState(session_date=day)
        m.bearish.session=legacy.BearishSessionState(session_date=day)
        m.trade_owner='NONE'
        t=deepcopy(tracker)
        gate=base.make_gate(t.frames)
        original_signal=gate.signal
        original_can_signal=gate.can_signal
        gate.signal=lambda event,available: original_signal(event,available) if legacy.direction(event)=='BEARISH' else None
        gate.can_signal=lambda side,at: side=='BEARISH' and original_can_signal(side,at)
        self.monitor=(m,t,gate)

    def boundary(self,c,g,bar,reference,tracker,manual_block=False):
        before=g.owner
        monitor_result=None
        at=bar.ts+core.timedelta(minutes=5)
        if before=='BULLISH' and self.reversal and self.monitor:
            mc,mt,mg=self.monitor
            mr=mc.bullish.previous_indicators or reference
            monitor_result=base.advance_boundary(mc,mg,bar,mr,mt)
            self.opposite_audit.append(dict(time=at.isoformat(),checks=monitor_result['checks'],
                policy_events=monitor_result['policy_events'],setups=monitor_result['setups'],
                confirmed=bool(monitor_result['entries'])))
        result=self.advance(c,g,bar,reference,tracker,manual_block=manual_block)
        current=result['current']
        if before=='BULLISH':
            dual=base.dual_exit('BULLISH',current)
            self.exit_audit.append(dict(time=at.isoformat(),rsi9=current.rsi9,
                ema3=current.ema3_rsi,wma21=current.wma21_rsi,
                rsi_below_wma=current.rsi9<current.wma21_rsi,
                ema_below_wma=current.ema3_rsi<current.wma21_rsi,
                original_dual_exit=dual,wma_below60=current.wma21_rsi<60,
                action='NORMAL_EXIT' if dual and current.wma21_rsi<60 else 'DEFER_WMA_GE60' if dual else 'HOLD_NO_DUAL_EXIT'))
        bear_entries=(monitor_result or {}).get('entries') or []
        if before=='BULLISH' and bear_entries and not result['entries'] and at.strftime('%H:%M')<'14:55':
            if len(bear_entries)!=1 or legacy.direction(bear_entries[0])!='BEARISH':
                raise ValueError('INVALID_OPPOSITE_CONFIRMATION')
            if g.owner=='BULLISH':
                event=legacy.StrategyEvent('STRUCTURAL_EXIT_BULLISH_RSI_CROSS_BELOW_WMA21',at,
                    None,'ACTIVE','IDLE',exit_reason='FULLY_CONFIRMED_OPPOSITE_BEARISH')
                closed=g.close(event,at,float(bar.close))
                if closed is None:raise ValueError('REVERSAL_EXIT_MISSING')
                result['exits'].append(closed)
            if g.owner=='NONE':
                event=bear_entries[0]
                # The monitor uses the unmodified complete bullish signal/followup gate.
                # Transfer the confirmed entry after the actual bearish exit.
                self.policy.reset_pending(g)
                g.owner='BEARISH';g.active=dict(time=at,price=float(bar.close))
                result['entries']=[replace(event,price=float(bar.close),entry_price=float(bar.close))]
                result['policy_events'].append(dict(event='RESEARCH_CONFIRMED_OPPOSITE_REVERSAL',
                    time=at.isoformat(),direction='BEARISH',entry_evidence=event.details))
                self.exit_audit[-1]['action']='EXIT_AND_REVERSE_BEARISH'
        if self.reversal:
            if g.owner=='BULLISH' and before!='BULLISH':self.start_monitor(c,tracker)
            elif g.owner!='BULLISH':self.monitor=None
        return result

def stats(trades):
    equity=peak=dd=0
    for t in sorted(trades,key=lambda t:t['exit_time']):
        equity+=t['points'];peak=max(peak,equity);dd=max(dd,peak-equity)
    return dict(trades=len(trades),winners=sum(t['points']>0 for t in trades),
        losers=sum(t['points']<0 for t in trades),
        winning_points=sum(max(0,t['points']) for t in trades),
        losing_points=sum(min(0,t['points']) for t in trades),net_points=equity,drawdown=dd)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input-zip',type=Path,required=True)
    ap.add_argument('--date',action='append')
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if base.VERSION!='bullish-gap2-full-wma2-2.0.0-wma40-reversal':
        raise ValueError('DEPLOYED_WMA40_REVERSAL_CONTROL_REQUIRED')
    warm,_=core.read_inputs(args.input_zip)
    days=args.date or [d for d,_ in warm if d.startswith('2026-10-')]
    if not days:raise ValueError('NO_OCTOBER_INPUT_SESSIONS')
    raw_by_day=dict(warm)
    from market_lab import hilega_combined_replay_v1 as replay
    args.output.mkdir(parents=True,exist_ok=True)
    results=[]
    lines=['# Bullish WMA60 exit: October', '',
        'Control = deployed bearish WMA40 + confirmed bullish reversal. All policies retain that change.',
        'Research only; completed5m; gross NIFTY points, no option fills/costs. No live changes.',
        'Bullish normal exit = original dual exit AND WMA<60 on the same boundary; equality holds.',
        'Reversal variant also closes bullish and enters fully confirmed bearish, whichever qualifies first.',
        'All normal bearish signal/followup checks required; monitor begins after actual bullish entry.',
        '14:55 cutoff unchanged. Only saved October sessions in the ZIP are evaluated.', '']
    for day in days:
        until=datetime.fromisoformat(day+'T14:55:00+05:30')
        try:
            raw=raw_by_day[day]
            baseline=core.run(base,legacy,warm,raw,day,5,until)
            original=replay.replay(day,raw,[(d,r) for d,r in warm if d<day])
            if signature(baseline['trades'])!=signature(original['trades']):
                raise ValueError('BASELINE_PARITY_FAILED')
            variants={'CURRENT':baseline}
            studies={}
            for key,reverse in [('BULLISH_WMA60_EXIT_ONLY',False),('BULLISH_WMA60_PLUS_BEARISH_REVERSAL',True)]:
                study=Study(reverse)
                result=core.run(study.policy,legacy,warm,raw,day,5,until)
                if result['open_trade']:raise ValueError('UNRESOLVED_POSITION')
                result.update(exit_checks=study.exit_audit,opposite_checks=study.opposite_audit)
                variants[key]=result;studies[key]=study
            row=dict(session_date=day,status='COMPLETE',baseline_parity='PASS',policies=variants)
            lines += ['## '+day,'','| Policy | Trades | Winning points | Losing points | Net points | Winners | Losers | Drawdown |',
                '|---|---:|---:|---:|---:|---:|---:|---:|']
            for key,result in variants.items():
                s=stats(result['trades']);result['stats']=s
                lines.append(f"| {key} | {s['trades']} | {s['winning_points']:+.2f} | {s['losing_points']:+.2f} | {s['net_points']:+.2f} | {s['winners']} | {s['losers']} | {s['drawdown']:.2f} |")
            lines+=['','| Policy | Direction | Setup | Qualified | Entry–exit | NIFTY points | Exit reason |',
                '|---|---|---|---|---|---:|---|']
            for key,result in variants.items():
                for t in result['trades']:
                    hm=lambda v:v[11:16] if v else '—'
                    lines.append(f"| {key} | {t['direction']} | {hm(t.get('setup'))} | {hm(t.get('qualified'))} | {hm(t['entry_time'])}–{hm(t['exit_time'])} | {t['points']:+.2f} | {t['exit_reason']} |")
            for key,study in studies.items():
                lines+=['','### '+key+' — bullish exit checks','',
                    '| Time | RSI9 | EMA3 RSI | WMA21 | Original dual exit | WMA <60 | Decision |',
                    '|---|---:|---:|---:|---|---|---|']
                for a in study.exit_audit:
                    lines.append(f"| {a['time'][11:16]} | {a['rsi9']:.3f} | {a['ema3']:.3f} | {a['wma21']:.3f} | {'✓' if a['original_dual_exit'] else '✗'} | {'✓' if a['wma_below60'] else '✗'} | {a['action']} |")
        except Exception as exc:
            row=dict(session_date=day,status='INCOMPLETE',issues=[type(exc).__name__+': '+str(exc)])
            lines+=['## '+day,'INCOMPLETE: '+row['issues'][0],'']
        results.append(row)
        (args.output/(day+'.json')).write_text(json.dumps(row,indent=2))
        print(json.dumps({k:v for k,v in row.items() if k!='policies'}),flush=True)
    report=dict(status='COMPLETE' if all(r['status']=='COMPLETE' for r in results) else 'INCOMPLETE',
        sessions=results,observation_only=True,orders_sent=False)
    (args.output/'report.json').write_text(json.dumps(report,indent=2))
    (args.output/'comparison.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines))
    print('REPORT:',args.output/'report.json')

if __name__=='__main__':main()
