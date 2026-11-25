"""Independent 3m RSI/EMA research engine. No application or broker imports."""
from collections import deque
from datetime import datetime,timedelta,time
from math import isfinite

VERSION='rsi-two-route-0.4.1-colour-only-reversal'
ROUTE_NAME='Normal Route + WMA_bypass'
ROUTE_ID='RSI_TWO_ROUTE'
PERIODS=(5,9,14,21,28)


class RSI:
    def __init__(self,period):
        self.period=period;self.previous=None;self.gains=[];self.losses=[];self.gain=None;self.loss=None
    def update(self,close):
        if not isfinite(close):raise ValueError('NONFINITE_CLOSE')
        if self.previous is None:self.previous=close;return None
        delta=close-self.previous;self.previous=close;up=max(delta,0.);down=max(-delta,0.)
        if self.gain is None:
            self.gains.append(up);self.losses.append(down)
            if len(self.gains)<self.period:return None
            self.gain=sum(self.gains)/self.period;self.loss=sum(self.losses)/self.period
        else:
            self.gain=((self.period-1)*self.gain+up)/self.period
            self.loss=((self.period-1)*self.loss+down)/self.period
        return (100. if self.gain>0 else 50.) if self.loss==0 else 100.-100./(1.+self.gain/self.loss)


class Indicators:
    def __init__(self):
        self.rsi={p:RSI(p) for p in PERIODS};self.window=deque(maxlen=21)
        self.high=None;self.low=None
    def update(self,bar):
        values={'rsi'+str(p):i.update(float(bar['close'])) for p,i in self.rsi.items()}
        if values['rsi9'] is not None:self.window.append(values['rsi9'])
        values['wma21_rsi9']=sum((i+1)*v for i,v in enumerate(self.window))/231. if len(self.window)==21 else None
        alpha=2./31.
        self.high=float(bar['high']) if self.high is None else alpha*bar['high']+(1-alpha)*self.high
        self.low=float(bar['low']) if self.low is None else alpha*bar['low']+(1-alpha)*self.low
        return dict(values,ema30_high=self.high,ema30_low=self.low)


def entry_checks(frame,side):
    bull=side=='CE';checks={}
    def compare(value,threshold):return None if value is None or threshold is None else value>threshold if bull else value<threshold
    checks['close_vs_ema30_high' if bull else 'close_vs_ema30_low']=None if frame.get('close') is None else compare(frame['close'],frame['ema30_high' if bull else 'ema30_low'])
    checks['signal_candle_colour']=compare(frame.get('close'),frame.get('open'))
    for period in PERIODS:checks['rsi'+str(period)+'_threshold']=compare(frame.get('rsi'+str(period)),55 if bull else 45)
    checks['wma21_rsi9_threshold']=compare(frame.get('wma21_rsi9'),50)
    return checks


def candle_strength(frame):
    o,h,l,c=(frame.get(k) for k in ('open','high','low','close'))
    valid=all(isinstance(v,(int,float)) and not isinstance(v,bool) and isfinite(v) for v in (o,h,l,c))
    valid=valid and h>l and l<=min(o,c)<=max(o,c)<=h
    if not valid:return dict(valid=False,body_pct=None,upper_wick_pct=None,lower_wick_pct=None)
    span=h-l
    return dict(valid=True,body_pct=100*abs(c-o)/span,upper_wick_pct=100*(h-max(o,c))/span,lower_wick_pct=100*(min(o,c)-l)/span)


def evaluate_entry(frame,side):
    checks=entry_checks(frame,side);shape=candle_strength(frame)
    ready=all(frame.get(k) is not None and isfinite(frame[k]) for k in
        ['rsi'+str(p) for p in PERIODS]+['wma21_rsi9','ema30_high','ema30_low'])
    price='close_vs_ema30_high' if side=='CE' else 'close_vs_ema30_low'
    common={k:checks[k] for k in (price,'signal_candle_colour')}
    common['indicators_ready']=ready
    passed=[p for p in PERIODS if checks['rsi'+str(p)+'_threshold'] is True]
    normal=dict(common, rsi_minimum_two=len(passed)>=2, wma21_rsi9_threshold=checks['wma21_rsi9_threshold'])
    bypass=dict(common, rsi_all_five=len(passed)==5)
    route_checks={'Normal Route':normal,'WMA_bypass':bypass}
    eligible={name:all(v is True for v in gates.values()) for name,gates in route_checks.items()}
    selected=next((name for name in ('Normal Route','WMA_bypass') if eligible[name]),None)
    # Bypass does not waive data availability. WMA may fail its threshold, but must be known.
    blockers=[] if selected else ['NO_ENTRY_ROUTE_QUALIFIED']
    return dict(checks=checks,candle_strength=shape,rsi_pass_count=len(passed),rsi_pass_periods=passed,
        route_checks=route_checks,eligible_routes=eligible,selected_route=selected,
        route_blockers={name:[k for k,v in gates.items() if v is not True] for name,gates in route_checks.items()},blockers=blockers)


def exit_checks(frame,side,variant='ALL_THREE'):
    bull=side=='CE'
    def opposite(a,b):return False if a is None or b is None else a<b if bull else a>b
    r5=opposite(frame.get('rsi5'),50);r9=opposite(frame.get('rsi9'),50)
    if variant!='ALL_THREE':raise ValueError('NORMAL_ROUTE_REQUIRES_ALL_THREE_EXIT')
    momentum=r5 and r9
    wma=opposite(frame.get('wma21_rsi9'),50)
    price=opposite(frame.get('close'),frame.get('ema30_low' if bull else 'ema30_high'))
    return dict(momentum_exit=momentum,wma50_exit=wma,opposite_ema_boundary_exit=price,
                all_three_exit=momentum and wma and price,rsi5_opposite50=r5,rsi9_opposite50=r9)


def excursion(trade,minutes):
    entry=datetime.fromisoformat(trade['entry_time']);end=datetime.fromisoformat(trade['exit_time'])
    sign=1 if trade['side']=='CE' else -1
    held=[r for r in minutes if entry<=datetime.fromisoformat(r['timestamp'])<end]
    peak=max([0.]+[sign*((r['high'] if sign==1 else r['low'])-trade['entry_price']) for r in held])
    adverse=min([0.]+[sign*((r['low'] if sign==1 else r['high'])-trade['entry_price']) for r in held])
    return dict(peak_positive_points=peak,giveback_points=peak-trade['points'],worst_unrealized_points=adverse)


def replay(day,bars,minutes,warmup_bars,variant='ALL_THREE',indicator_factory=Indicators):
    if variant!='ALL_THREE':raise ValueError('NORMAL_ROUTE_REQUIRES_ALL_THREE_EXIT')
    tracker=indicator_factory()
    for b in warmup_bars:tracker.update(b)
    indexed={datetime.fromisoformat(r['timestamp']):r for r in minutes}
    if len(indexed)!=len(minutes):raise ValueError('DUPLICATE_MINUTE')
    special=day=='2026-11-08'
    count=23 if special else 125
    if len(bars)!=count:raise ValueError('COMPLETE_3M_SESSION_REQUIRED')
    start=datetime.fromisoformat(day+('T14:21:00+05:30' if special else 'T09:15:00+05:30'))
    if [datetime.fromisoformat(b['start']) for b in bars]!=[start+timedelta(minutes=3*i) for i in range(count)]:raise ValueError('CANDLE_GRID_INVALID')
    audits=[];trades=[];active=None
    for bar in bars:
        boundary=datetime.fromisoformat(bar['start'])+timedelta(minutes=3)
        at=boundary.isoformat();frame=dict(bar,**tracker.update(bar))
        evaluations={side:evaluate_entry(frame,side) for side in ('CE','PE')}
        candidates={side:ev['checks'] for side,ev in evaluations.items()}
        qualified={side:ev['selected_route'] is not None for side,ev in evaluations.items()}
        before=active['side'] if active else None;events=[]
        closing=boundary.time()>=time(15,30)
        # Signals use only the completed bar. Fills use the next minute OPEN,
        # never that minute's high/low/close. Session end uses exact 15:29 close.
        fill=float(indexed[boundary]['open']) if not closing else float(indexed[boundary-timedelta(minutes=1)]['close'])
        exits=exit_checks(frame,active['side'],variant) if active else None
        opposite=('PE' if active['side']=='CE' else 'CE') if active else None
        reversal=bool(active and not closing and qualified[opposite])
        if exits is not None:exits.update(opposite_entry_exit=reversal,opposite_entry_route=evaluations[opposite]['selected_route'] if reversal else None)
        if active and (closing or reversal or exits['all_three_exit']):
            reasons=['SESSION_END_1530'] if closing else ['QUALIFIED_OPPOSITE_ENTRY'] if reversal else ['ALL_THREE_MOMENTUM_WMA_PRICE']
            sign=1 if active['side']=='CE' else -1
            active.update(exit_signal_time=at,exit_time=at,exit_price=fill,points=sign*(fill-active['entry_price']),exit_reasons=reasons,
                exit_frame=frame,exit_checks=exits,exit_fill_basis='EXACT_1529_CLOSE' if closing else 'NEXT_MINUTE_OPEN')
            active.update(excursion(active,minutes));trades.append(active)
            events.append(dict(event='EXIT',side=active['side'],trade_id=active['trade_id'],fill=fill,reasons=reasons));active=None
        if not closing and active is None:
            sides=[side for side in qualified if qualified[side]]
            if len(sides)>1:raise ValueError('CONTRADICTORY_SIGNALS')
            if sides:
                side=sides[0];route=evaluations[side]['selected_route'];active=dict(route_name=route,route_id='NORMAL_ROUTE' if route=='Normal Route' else 'WMA_BYPASS',entry_rsi_pass_count=evaluations[side]['rsi_pass_count'],entry_candle_strength=evaluations[side]['candle_strength'],trade_id=day+'-'+str(len(trades)+1).zfill(3),side=side,
                    entry_candle_start=bar['start'],entry_signal_time=at,entry_time=at,entry_price=fill,
                    entry_fill_basis='NEXT_MINUTE_OPEN',entry_frame=frame,entry_checks=evaluations[side]['route_checks'][route],entry_evaluation=evaluations[side])
                events.append(dict(event='ENTRY',route_name=route,side=side,trade_id=active['trade_id'],fill=fill))
        outcome={}
        for side in ('CE','PE'):
            entered=any(e['event']=='ENTRY' and e['side']==side for e in events)
            blockers=list(evaluations[side]['blockers'])
            if not entered and closing:blockers.append('SESSION_CLOSED')
            elif not entered and active is not None:blockers.append('ACTIVE_'+active['side']+'_OWNER')
            outcome[side]=dict(status='ENTRY' if entered else 'QUALIFIED_ALREADY_ACTIVE' if qualified[side] and active else 'WAIT',
                **{k:v for k,v in evaluations[side].items() if k!='blockers'},blockers=blockers)
        audits.append(dict(route_name=ROUTE_NAME,route_id=ROUTE_ID,decision_time=at,frame=frame,owner_before=before,owner_after=active['side'] if active else None,
            entry_evaluation=outcome,exit_evaluation=exits,events=events))
    if active:raise ValueError('SESSION_EXIT_MISSING')
    summary=dict(trades=len(trades),winners=sum(t['points']>0 for t in trades),losers=sum(t['points']<0 for t in trades),
        net_points=sum(t['points'] for t in trades),peak_positive_points=sum(t['peak_positive_points'] for t in trades),
        giveback_points=sum(t['giveback_points'] for t in trades),qualified_candles={side:sum(a['entry_evaluation'][side]['selected_route'] is not None for a in audits) for side in ('CE','PE')})
    return dict(route_name=ROUTE_NAME,route_id=ROUTE_ID,strategy_version=VERSION,session_date=day,exit_variant=variant,trades=trades,audit=audits,summary=summary,
        observation_only=True,broker_orders_sent=False,option_premiums_tested=False,
        fill_model='COMPLETED_3M_SIGNAL_NEXT_1M_OPEN; SESSION_EXIT_EXACT_1529_CLOSE',fees_and_slippage_included=False)
