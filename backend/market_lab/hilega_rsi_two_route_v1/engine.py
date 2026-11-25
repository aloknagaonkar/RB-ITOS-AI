"""Incremental policy. No network, app state, credentials or execution transport."""
from collections import deque
from datetime import datetime, timedelta, time
from .reference import (Indicators, RSI, PERIODS, evaluate_entry, exit_checks, excursion,
                        ROUTE_NAME, ROUTE_ID)
from . import STRATEGY_ID, VERSION

class Engine:
    def __init__(self, day, warmup_bars=()):
        self.day = day
        self.tracker = Indicators()
        for bar in warmup_bars:
            self.tracker.update(bar)
        self.active = None
        self.trades = []
        self.audits = []

    def advance(self, bar, minutes, entry_block_reason=None):
        day = self.day
        offset = len(self.audits)
        start = datetime.fromisoformat(day + ('T14:21:00+05:30' if day == '2026-11-08' else 'T09:15:00+05:30'))
        if datetime.fromisoformat(bar['start']) != start + timedelta(minutes=3*offset):
            raise ValueError('NONSEQUENTIAL_COMPLETED_BAR')
        if offset >= (23 if day == '2026-11-08' else 125):
            raise ValueError('SESSION_ALREADY_COMPLETE')
        indexed = {datetime.fromisoformat(r['timestamp']): r for r in minutes}
        if len(indexed) != len(minutes):
            raise ValueError('DUPLICATE_MINUTE')
        # Enforce fill readiness before mutating indicator state.
        boundary = datetime.fromisoformat(bar['start']) + timedelta(minutes=3)
        closing = boundary.time() >= time(15,30)
        float(indexed[boundary-timedelta(minutes=1)]['close'] if closing else indexed[boundary]['open'])
        tracker, active, trades, audits = self.tracker, self.active, self.trades, self.audits
        variant = 'ALL_THREE'
        boundary=datetime.fromisoformat(bar['start'])+timedelta(minutes=3)
        at=boundary.isoformat();frame=dict(bar,**tracker.update(bar))
        evaluations={side:evaluate_entry(frame,side) for side in ('CE','PE')}
        candidates={side:ev['checks'] for side,ev in evaluations.items()}
        qualified={side:ev['selected_route'] is not None and not entry_block_reason for side,ev in evaluations.items()}
        before=active['side'] if active else None;events=[];midpoint_closed_side=None
        closing=boundary.time()>=time(15,30)
        # Signals use only the completed bar. Fills use the next minute OPEN,
        # never that minute's high/low/close. Session end uses exact 15:29 close.
        fill=float(indexed[boundary]['open']) if not closing else float(indexed[boundary-timedelta(minutes=1)]['close'])
        exits=exit_checks(frame,active['side'],variant) if active else None
        opposite=('PE' if active['side']=='CE' else 'CE') if active else None
        reversal=bool(active and not closing and qualified[opposite])
        if exits is not None:exits.update(opposite_entry_exit=reversal,opposite_entry_route=evaluations[opposite]['selected_route'] if reversal else None)
        midpoint=(active['entry_frame']['high']+active['entry_frame']['low'])/2 if active else None
        midpoint_breach=bool(active and (frame['close']<midpoint if active['side']=='CE' else frame['close']>midpoint))
        midpoint_exit=bool(midpoint_breach and exits['momentum_exit'])
        if exits is not None:exits.update(signal_midpoint=midpoint,signal_midpoint_price_breach=midpoint_breach,signal_midpoint_rsi_confirmed_exit=midpoint_exit)
        if active and (closing or reversal or midpoint_exit or exits['all_three_exit']):
            reasons=['SESSION_END_1530'] if closing else ['QUALIFIED_OPPOSITE_ENTRY'] if reversal else ['SIGNAL_MIDPOINT_AND_RSI5_RSI9'] if midpoint_exit else ['ALL_THREE_MOMENTUM_WMA_PRICE']
            if midpoint_exit:midpoint_closed_side=active['side']
            sign=1 if active['side']=='CE' else -1
            active.update(exit_signal_time=at,exit_time=at,exit_price=fill,points=sign*(fill-active['entry_price']),exit_reasons=reasons,
                exit_frame=frame,exit_checks=exits,exit_fill_basis='EXACT_1529_CLOSE' if closing else 'NEXT_MINUTE_OPEN')
            active.update(excursion(active,minutes));trades.append(active)
            events.append(dict(event='EXIT',side=active['side'],trade_id=active['trade_id'],fill=fill,reasons=reasons));active=None
        if not closing and active is None:
            sides=[side for side in qualified if qualified[side] and side!=midpoint_closed_side]
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
            if entry_block_reason:blockers.append(entry_block_reason)
            if not entered and closing:blockers.append('SESSION_CLOSED')
            elif not entered and active is not None:blockers.append('ACTIVE_'+active['side']+'_OWNER')
            elif not entered and side==midpoint_closed_side:blockers.append('MIDPOINT_EXIT_SAME_CANDLE_REENTRY_BLOCKED')
            outcome[side]=dict(status='ENTRY' if entered else 'QUALIFIED_ALREADY_ACTIVE' if qualified[side] and active else 'WAIT',
                **{k:v for k,v in evaluations[side].items() if k!='blockers'},blockers=blockers)
        audits.append(dict(route_name=ROUTE_NAME,route_id=ROUTE_ID,decision_time=at,frame=frame,owner_before=before,owner_after=active['side'] if active else None,
            entry_evaluation=outcome,exit_evaluation=exits,events=events))
        self.active = active
        return audits[-1]

    def snapshot(self):
        return dict(day=self.day, active=self.active, trades=self.trades, audits=self.audits,
            indicator=dict(rsi={str(p):vars(r) for p,r in self.tracker.rsi.items()},
                           window=list(self.tracker.window), high=self.tracker.high, low=self.tracker.low))

    @classmethod
    def restore(cls, state):
        result=cls(state['day'])
        result.active=state['active'];result.trades=state['trades'];result.audits=state['audits']
        i=state['indicator'];result.tracker.high=i['high'];result.tracker.low=i['low']
        result.tracker.window=deque(i['window'],maxlen=21)
        for p in PERIODS:
            result.tracker.rsi[p].__dict__.update(i['rsi'][str(p)])
        return result

    def result(self):
        trades=self.trades
        open_metrics=None
        if self.active and self.audits:
            sign=1 if self.active['side']=='CE' else -1
            entry=self.active['entry_price']
            held=[a['frame'] for a in self.audits if a['frame']['start']>=self.active['entry_time']]
            current=sign*(self.audits[-1]['frame']['close']-entry) if held else 0.
            peak=max([0.]+[sign*(b['high' if sign==1 else 'low']-entry) for b in held])
            open_metrics=dict(as_of=self.audits[-1]['decision_time'],unrealized_points=current,
                              peak_positive_points=peak,giveback_points=peak-current,
                              mark_basis='LAST_COMPLETED_3M_CLOSE_MODELED' if held else 'ENTRY_OPEN_MODELED')
        return dict(open_metrics=open_metrics,strategy_id=STRATEGY_ID,strategy_version=VERSION,
            research_reference='rsi-two-route-0.5.1-confirmed-midpoint-research',
            session_date=self.day, route_name=ROUTE_NAME, route_id=ROUTE_ID,
            trades=trades,audit=self.audits,active_trade=self.active,
            owner=self.active['side'] if self.active else None,
            summary=dict(trades=len(trades),winners=sum(t['points']>0 for t in trades),
                losers=sum(t['points']<0 for t in trades),net_points=sum(t['points'] for t in trades),
                peak_positive_points=sum(t['peak_positive_points'] for t in trades),
                giveback_points=sum(t['giveback_points'] for t in trades),
                qualified_candles={s:sum(a['entry_evaluation'][s]['selected_route'] is not None for a in self.audits) for s in ('CE','PE')}),
            execution_mode='SIMULATION_ONLY',broker_orders_sent=False,
            fill_model='COMPLETED_3M_SIGNAL_NEXT_1M_OPEN; SESSION_EXIT_EXACT_1529_CLOSE',
            fees_and_slippage_included=False,option_premiums_tested=False)
