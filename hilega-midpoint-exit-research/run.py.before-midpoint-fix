"""Offline hybrid replay: existing route plus recorded-setup body breakout route."""
import argparse,json
from pathlib import Path
from datetime import datetime,date,time,timedelta
import timing_core as core
from rules import qualify,decision,midpoint_exit

def replay(warm,raw,day,prepared=None,protect_midpoint=False):
    p,l=core.policy5,core.legacy5
    if prepared is not None:
        from copy import deepcopy
        c,tracker,count=deepcopy(prepared)
    else:
        c=l.ExitFirstCanonical();tracker=p.PriceFrames();count=0
        for d,rows in warm:
            if d>=day:continue
            for bar in core.aggregate(rows,d,5,datetime.combine(date.fromisoformat(d),time(15,30),core.IST)):
                c.on_bar(bar);tracker.seed(bar)
            count+=1
    if count<20:raise ValueError('INSUFFICIENT_WARMUP')
    opening=c.bullish.previous_indicators
    c.bullish.session=l.SessionState(session_date=date.fromisoformat(day))
    c.bearish.session=l.BearishSessionState(session_date=date.fromisoformat(day))
    for engine in (c.bullish,c.bearish):engine.previous_indicators=None;engine.previous_bar=None
    c.trade_owner='NONE';c.session_date=date.fromisoformat(day)
    g=p.make_gate(tracker.frames);active=None;waiting=None;trades=[];audit=[]
    cutoff=datetime.combine(date.fromisoformat(day),time(14,55),core.IST)
    bars={b.ts+timedelta(minutes=5):b for b in core.aggregate(raw,day,5,cutoff)}
    for minute in core.aggregate(raw,day,1,cutoff):
        at=minute.ts+timedelta(minutes=1)
        # Only extra-route positions receive the new1m exit. Strict close, not wick.
        # Cutoff keeps its original14:55open mark and overrides this check.
        if (protect_midpoint and at<cutoff and active is not None
                and active.get('route')=='BODY50_1M_BREAKOUT'
                and at>datetime.fromisoformat(active['entry_time'])):
            midpoint=active['evidence']['midpoint']
            breached=midpoint_exit(active['direction'],float(minute.close),midpoint)
            audit.append(dict(time=at.isoformat(),action='ACTIVE_MIDPOINT_EXIT_CHECK',
                direction=active['direction'],close=float(minute.close),midpoint=midpoint,passed=breached))
            if breached:
                event=p.StrategyEvent('RESEARCH_MIDPOINT_EXIT',at,None,'ACTIVE','IDLE',exit_reason='POST_ENTRY_1M_SIGNAL_MIDPOINT_REVERSED')
                closed=g.close(event,at,float(minute.close))
                if closed is None:raise ValueError('MIDPOINT_EXIT_NOT_CLOSED')
                active.update(exit_time=at.isoformat(),exit_price=closed.price,points=closed.points,exit_reason=closed.exit_reason)
                trades.append(active);active=None;waiting=None;p.reset_pending(g)
                audit.append(dict(time=at.isoformat(),action='MIDPOINT_EXIT',price=closed.price,points=closed.points))
        # A completed 5m boundary takes precedence over the 1m waiting check.
        if at in bars:
            bar=bars[at];ref=c.bullish.previous_indicators or opening
            result=p.advance_boundary(c,g,bar,ref,tracker)
            for event in result['exits']:
                if active is None:raise ValueError('EXIT_WITHOUT_ENTRY')
                active.update(exit_time=at.isoformat(),exit_price=event.price,points=event.points,exit_reason=event.exit_reason)
                trades.append(active);active=None
            for event in result['entries']:
                if active is not None:raise ValueError('OVERLAPPING_ENTRY')
                active=dict(direction=l.direction(event),entry_time=at.isoformat(),entry_price=event.entry_price,route='EXISTING',setup=event.details.get('wma_gap',{}).get('signal_available_at'),entry_evidence=event.details.get('combined_entry'),qualified=event.details.get('qualified_signal_time'))
                waiting=None
            if waiting and any(e.get('event')=='QUALIFIED_OPPOSITE_WATCH_OVERRIDE' and e.get('direction')!=waiting['direction'] for e in result['policy_events']):
                audit.append(dict(time=at.isoformat(),action='CANCEL_QUALIFIED_OPPOSITE',signal=waiting));waiting=None
            if g.owner=='NONE' and at<cutoff:
                for setup in result['setups']:
                    candidate=qualify(setup['direction'],result['frame'])
                    if candidate:
                        # Preserve earliest same-direction reference; new opposite eligible setup replaces it.
                        if waiting is None or waiting['direction']!=candidate['direction']:
                            waiting=dict(**candidate,signal_time=at.isoformat(),setup_source=setup['source'],signal_frame=dict(result['frame']))
                            audit.append(dict(time=at.isoformat(),action='ARM_BODY_BREAKOUT',signal=waiting))
            audit.append(dict(time=at.isoformat(),action='FIVE_MINUTE_EVALUATION',frame=result['frame'],setups=result['setups'],checks=result['checks'],exit_validation=result['exit_validation'],opposite_confirmation=result.get('opposite_confirmation'),policy_events=result['policy_events'],entries=[dict(direction=l.direction(e),time=at.isoformat(),price=e.entry_price) for e in result['entries']],exits=[dict(time=at.isoformat(),price=e.price,points=e.points,reason=e.exit_reason) for e in result['exits']]))
        if at>=cutoff:break
        if waiting and g.owner=='NONE' and at>datetime.fromisoformat(waiting['signal_time']):
            action=decision(waiting,float(minute.close))
            audit.append(dict(time=at.isoformat(),action=action,close=float(minute.close),signal=waiting))
            if action=='CANCEL_MIDPOINT':waiting=None
            elif action=='ENTRY':
                p.reset_pending(g);g.owner=waiting['direction'];g.active=dict(time=at,price=float(minute.close))
                active=dict(direction=g.owner,entry_time=at.isoformat(),entry_price=float(minute.close),route='BODY50_1M_BREAKOUT',setup=waiting['signal_time'],evidence=waiting,followup=dict(open=minute.open,high=minute.high,low=minute.low,close=minute.close),qualified=waiting['signal_time'])
                if g.owner=='BEARISH':g._bullish_exit_monitor=p._start_bullish_exit_monitor(c,tracker)
                waiting=None
    if active:
        row=next((r for r in raw if datetime.fromisoformat(r['timestamp'])==cutoff),None)
        if row is None:raise ValueError('CUTOFF_OPEN_MISSING')
        price=float(row['open']);s=1 if active['direction']=='BULLISH' else -1
        active.update(exit_time=cutoff.isoformat(),exit_price=price,points=s*(price-active['entry_price']),exit_reason='SESSION_CUTOFF_1455');trades.append(active)
    return dict(trades=trades,audit=audit,net_points=sum(t['points'] for t in trades))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input-zip',type=Path,required=True);ap.add_argument('--session-input',type=Path,required=True);ap.add_argument('--date',default='2026-10-22');ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if core.policy5.VERSION!='bullish-gap2-full-wma2-2.0.0-wma40-reversal':raise ValueError('POLICY_VERSION_MISMATCH')
    warm,records=core.read_inputs(a.input_zip);data=json.loads(a.session_input.read_text())
    if data['session_date']!=a.date:raise ValueError('SESSION_DATE_MISMATCH')
    until=datetime.fromisoformat(a.date+'T14:55:00+05:30');raw=data['candles']
    baseline=core.run(core.policy5,core.legacy5,warm,raw,a.date,5,until)
    records=[r for r in records if str((r.get('payload') or {}).get('decision_timestamp') or r.get('event_time','')).startswith(a.date)]
    proof=core.parity(baseline,records,until)
    if proof['status']!='PASS':raise ValueError('BASELINE_PARITY_FAILED:'+json.dumps(proof))
    tested=replay(warm,raw,a.date);protected=replay(warm,raw,a.date,protect_midpoint=True);a.output.mkdir(parents=True,exist_ok=True)
    report=dict(session_date=a.date,baseline_parity=proof,policies={'DEPLOYED_5M':baseline,'BODY50_1M_WAIT':tested,'BODY50_1M_MIDPOINT_EXIT':protected},research_only=True)
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    lines=['# Body-cross + 1m breakout waiting replay','', 'Gross NIFTY points; no fills/costs. Existing entry route retained. No live changes.','', '| Policy | Direction | Setup | Entry–exit IST | Route | NIFTY points | Exit reason |','|---|---|---|---|---|---:|---|']
    for name,result in report['policies'].items():
        for t in result['trades']:
            lines.append(f"| {name} | {t['direction']} | {(t.get('setup') or '')[11:16]} | {t['entry_time'][11:16]}–{t['exit_time'][11:16]} | {t.get('route','EXISTING')} | {t['points']:+.2f} | {t['exit_reason']} |")
        lines.append(f"\n{name}: {sum(t['points'] for t in result['trades']):+.2f} points\n")
    (a.output/'comparison.md').write_text('\n'.join(lines));print('\n'.join(lines))
if __name__=='__main__':main()
