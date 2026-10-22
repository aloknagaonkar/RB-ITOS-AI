"""Prepared warmup clones; same session loop as timing_core.run."""
from copy import deepcopy
from timing_core import *

def run_prepared(policy, legacy, prepared, raw, day, interval, until):
    c, tracker, count = deepcopy(prepared)
    if count < 20:raise ValueError("INSUFFICIENT_WARMUP")
    opening = c.bullish.previous_indicators
    c.bullish.session = legacy.SessionState(session_date=date.fromisoformat(day))
    c.bearish.session = legacy.BearishSessionState(session_date=date.fromisoformat(day))
    for engine in (c.bullish,c.bearish):
        engine.previous_indicators = None
        engine.previous_bar = None
    c.trade_owner = 'NONE'
    c.session_date = date.fromisoformat(day)
    gate = policy.make_gate(tracker.frames)
    closed, audit, active = [], [], None
    cutoff = datetime.combine(date.fromisoformat(day), time(14,55), IST)
    for bar in aggregate(raw, day, interval, min(until, cutoff)):
        reference = c.bullish.previous_indicators or opening
        result = policy.advance_boundary(c, gate, bar, reference, tracker)
        at = bar.ts + timedelta(minutes=interval)
        for event in result['exits']:
            if active is None:
                raise ValueError('EXIT_WITHOUT_ENTRY')
            active.update(exit_time=at.isoformat(), exit_price=event.price,
                          points=event.points, exit_reason=event.exit_reason)
            closed.append(active)
            active = None
        for event in result['entries']:
            if active is not None:
                raise ValueError('OVERLAPPING_POSITION')
            active = dict(direction=legacy.direction(event), entry_time=at.isoformat(),
                entry_price=event.entry_price, setup=event.details['wma_gap']['signal_available_at'],
                qualified=event.details.get('qualified_signal_time'),
                entry_evidence=event.details.get('combined_entry'))
        audit.append(dict(time=at.isoformat(), frame=result['frame'],
            checks=result['checks'], setups=result['setups'],
            policy_events=result['policy_events'], exit_validation=result['exit_validation']))
    if active is not None and until >= cutoff:
        row = next((r for r in raw if datetime.fromisoformat(r['timestamp']) == cutoff), None)
        if row is None:
            raise ValueError('CUTOFF_OPEN_REQUIRED')
        price = float(row['open'])
        active.update(exit_time=cutoff.isoformat(), exit_price=price,
            points=(price-active['entry_price'])*(1 if active['direction']=='BULLISH' else -1),
            exit_reason='SESSION_CUTOFF_1455')
        closed.append(active)
        active = None
    mark = next((float(r['close']) for r in raw
        if datetime.fromisoformat(r['timestamp']) == until-timedelta(minutes=1)), None)
    if mark is None:
        raise ValueError('COMMON_HORIZON_MARK_MISSING')
    if active:
        active.update(mark_time=until.isoformat(), mark_price=mark,
            unrealized_points=(mark-active['entry_price'])*(1 if active['direction']=='BULLISH' else -1))
    return dict(interval=interval, warmup_sessions=count, trades=closed,
        open_trade=active, audit=audit,
        closed_points=sum(t['points'] for t in closed))
