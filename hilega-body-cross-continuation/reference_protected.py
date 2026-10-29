"""Offline hybrid replay: existing route plus recorded-setup body breakout route."""
import argparse,json
from pathlib import Path
from datetime import datetime,date,time,timedelta
import core
from strict_rules import qualify,decision,candidates,midpoint_exit
from copy import deepcopy

def support_monitor(c, tracker, gate, side):
    # Separate flat observer. Copy pending confirmation state before entry reset.
    # Canonical session is reset so an independently entered position cannot
    # prevent subsequent existing-strategy setup generation.
    p,l=core.policy5,core.legacy5
    mc=deepcopy(c);mt=deepcopy(tracker)
    mc.bullish.session=l.SessionState(session_date=mc.session_date)
    mc.bearish.session=l.BearishSessionState(session_date=mc.session_date)
    mc.trade_owner='NONE'
    mg=p.make_gate(mt.frames)
    state={k:v for k,v in gate.__dict__.items() if k!='_bullish_exit_monitor'}
    mg.__dict__.update(deepcopy(state));mg.owner='NONE';mg.active=None
    mg.pending={k:v for k,v in mg.pending.items() if k==side}
    if getattr(mg,'watch_side',None)!=side:
        mg.watch_side=None;mg.watch_at=None
    if getattr(mg,'followup_signal',None) and mg.followup_signal['direction']!=side:
        mg.followup_signal=None
    mg.followup_price_permission=None
    signal,can_signal=mg.signal,mg.can_signal
    mg.signal=lambda event,at:signal(event,at) if l.direction(event)==side else None
    mg.can_signal=lambda requested,at:requested==side and can_signal(requested,at)
    return mc,mt,mg


def record_support(active, at, result, audit):
    evidence=[e for e in result['entries'] if core.legacy5.direction(e)==active['direction']]
    if not evidence:return False
    e=evidence[0]
    info=dict(time=at.isoformat(),action='EXISTING_STRATEGY_SUPPORTS_ACTIVE_TRADE',
              direction=active['direction'],independent_entry_time=active['entry_time'],
              independent_entry_price=active['entry_price'],
              support_confirmation_price=e.entry_price,
              confirmation_evidence=deepcopy(e.details),frame=deepcopy(result['frame']),
              informational_only=True,additional_position=False)
    active.setdefault('existing_support',[]).append(deepcopy(info));audit.append(info)
    return True


def protection_check(active, at, close, cutoff):
    if (active is None or active.get('route')!='INDEPENDENT_BODY60_1M_BREAKOUT'
            or at>=cutoff or at<=datetime.fromisoformat(active['entry_time'])):
        return None
    midpoint=active['evidence']['midpoint']
    return dict(time=at.isoformat(),action='ACTIVE_MIDPOINT_EXIT_CHECK',
        direction=active['direction'],close=close,midpoint=midpoint,
        entry_time=active['entry_time'],signal_time=active['setup'],
        passed=midpoint_exit(active['direction'],close,midpoint))


def replay(warm,raw,day,prepared=None):
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
    g=p.make_gate(tracker.frames);active=None;waiting=None;trades=[];audit=[];support=None
    cutoff=datetime.combine(date.fromisoformat(day),time(14,55),core.IST)
    bars={b.ts+timedelta(minutes=5):b for b in core.aggregate(raw,day,5,cutoff)}
    for minute in core.aggregate(raw,day,1,cutoff):
        at=minute.ts+timedelta(minutes=1)
        # Post-entry protection uses a completed1m close, never wick/intrabar price.
        # At14:55 the existing cutoff takes priority. At other5m boundaries,
        # protection runs first and closes through the shared gate exactly once.
        protection=protection_check(active,at,float(minute.close),cutoff)
        if protection is not None:
            audit.append(protection)
            if protection['passed']:
                event_type=('STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21' if active['direction']=='BULLISH'
                    else 'STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21')
                event=p.StrategyEvent(event_type,at,None,'ACTIVE','IDLE',
                    exit_reason='POST_ENTRY_1M_SIGNAL_MIDPOINT_REVERSED')
                closed=g.close(event,at,float(minute.close))
                if closed is None:raise ValueError('MIDPOINT_EXIT_NOT_CLOSED')
                active.update(exit_time=at.isoformat(),exit_price=closed.price,
                    points=closed.points,exit_reason=closed.exit_reason)
                trades.append(active);active=None;waiting=None;support=None
                p.reset_pending(g)
                audit.append(dict(time=at.isoformat(),action='MIDPOINT_EXIT',
                    price=closed.price,points=closed.points,exit_reason=closed.exit_reason))
        # A completed 5m boundary takes precedence over the 1m waiting check.
        if at in bars:
            bar=bars[at];ref=c.bullish.previous_indicators or opening
            if support is not None and active is not None:
                mc,mt,mg=support
                sr=p._advance_standard(mc,mg,bar,mc.bullish.previous_indicators or opening,mt)
                audit.append(dict(time=at.isoformat(),action='EXISTING_SUPPORT_MONITOR_CHECK',
                    direction=active['direction'],checks=sr['checks'],policy_events=sr['policy_events'],
                    frame=sr['frame'],informational_only=True))
                if record_support(active,at,sr,audit):support=None
            result=p.advance_boundary(c,g,bar,ref,tracker)
            for event in result['exits']:
                if active is None:raise ValueError('EXIT_WITHOUT_ENTRY')
                active.update(exit_time=at.isoformat(),exit_price=event.price,points=event.points,exit_reason=event.exit_reason)
                trades.append(active);active=None;support=None
            for event in result['entries']:
                if active is not None:raise ValueError('OVERLAPPING_ENTRY')
                active=dict(direction=l.direction(event),entry_time=at.isoformat(),entry_price=event.entry_price,route='EXISTING',setup=event.details.get('wma_gap',{}).get('signal_available_at'),entry_evidence=event.details.get('combined_entry'),qualified=event.details.get('qualified_signal_time'))
                waiting=None
            if waiting and any(e.get('event')=='QUALIFIED_OPPOSITE_WATCH_OVERRIDE' and e.get('direction')!=waiting['direction'] for e in result['policy_events']):
                audit.append(dict(time=at.isoformat(),action='CANCEL_QUALIFIED_OPPOSITE',signal=waiting));waiting=None
            if g.owner=='NONE' and at<cutoff:
                for candidate in candidates(result['frame']):
                    setup=dict(source='INDEPENDENT_BODY_EMA10_CROSS')
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
                support=support_monitor(c,tracker,g,waiting['direction'])
                p.reset_pending(g);g.owner=waiting['direction'];g.active=dict(time=at,price=float(minute.close))
                active=dict(direction=g.owner,entry_time=at.isoformat(),entry_price=float(minute.close),route='INDEPENDENT_BODY60_1M_BREAKOUT',setup=waiting['signal_time'],evidence=waiting,followup=dict(open=minute.open,high=minute.high,low=minute.low,close=minute.close),qualified=waiting['signal_time'])
                if g.owner=='BEARISH':g._bullish_exit_monitor=p._start_bullish_exit_monitor(c,tracker)
                waiting=None
    if active:
        row=next((r for r in raw if datetime.fromisoformat(r['timestamp'])==cutoff),None)
        if row is None:raise ValueError('CUTOFF_OPEN_MISSING')
        price=float(row['open']);s=1 if active['direction']=='BULLISH' else -1
        active.update(exit_time=cutoff.isoformat(),exit_price=price,points=s*(price-active['entry_price']),exit_reason='SESSION_CUTOFF_1455');trades.append(active)
    return dict(trades=trades,audit=audit,net_points=sum(t['points'] for t in trades))
