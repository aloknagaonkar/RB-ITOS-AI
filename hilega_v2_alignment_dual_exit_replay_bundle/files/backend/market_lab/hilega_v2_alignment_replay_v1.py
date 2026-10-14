"""Isolated historical research policy. No live adapters or broker operations."""
from __future__ import annotations
import copy, json, hashlib
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, date, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from .domain import IST
from .hilega_directional_coordinator_v1 import (HilegaDirectionalCoordinatorV1, DirectionalDecision,
 BULLISH_ENTRY_EVENTS,BEARISH_ENTRY_EVENTS,BULLISH_EXIT_EVENTS,BEARISH_EXIT_EVENTS)
from .hilega_milega_strategy_v1 import SessionState,StrategyEvent
from .hilega_milega_bearish_strategy_v1 import BearishSessionState
from .hilega_milega_historical_replay_v1 import aggregate_exact_5m
STRATEGY_ID = 'HILEGA_WMA_GAP_V2_LIVE_SHADOW'
ENTRY_TYPES = BULLISH_ENTRY_EVENTS | BEARISH_ENTRY_EVENTS
EXIT_TYPES = BULLISH_EXIT_EVENTS | BEARISH_EXIT_EVENTS

def direction(event):
    return 'BEARISH' if event.event_type in BEARISH_ENTRY_EVENTS | BEARISH_EXIT_EVENTS else 'BULLISH'

class ExitFirstCanonical(HilegaDirectionalCoordinatorV1):
    """Only V2's canonical setup stream allows exit-boundary reversals."""
    def _coordinate(self, *, bar, bullish_events, bearish_events):
        old = self.trade_owner
        opposite = 'BEARISH' if old == 'BULLISH' else 'BULLISH'
        engine = self.bearish if opposite == 'BEARISH' else self.bullish
        saved = deepcopy(engine.session)
        new_entries = self._entry_events(bearish_events if opposite == 'BEARISH' else bullish_events, opposite)
        exiting = self._exit_events(bullish_events if old == 'BULLISH' else bearish_events, old)
        decision = super()._coordinate(bar=bar, bullish_events=bullish_events, bearish_events=bearish_events)
        if old != 'NONE' and exiting and new_entries and bar.ts.time() < time(14,50):
            engine.session = saved
            self.trade_owner = opposite
            accepted = tuple(e for e in decision.accepted_events if e.event_type in EXIT_TYPES) + tuple(new_entries) + tuple(e for e in decision.accepted_events if e.event_type not in EXIT_TYPES)
            decision = replace(decision, trade_owner_after=opposite, accepted_events=accepted,
                suppressed_events=tuple(e for e in decision.suppressed_events if e not in new_entries),
                bullish_state=self.bullish.session.name, bearish_state=self.bearish.session.name,
                bullish_armed=self.bullish.session.armed, bearish_armed=self.bearish.session.armed,
                note='EXIT_FIRST; SAME_CANDLE_CANONICAL_SETUP_ALLOWED')
        return decision

class WmaGapGate:
    """Pure deterministic gate shared by live processing and offline tests."""
    def __init__(self):
        self.owner='NONE'; self.active=None; self.pending={}; self.previous=None; self.locked=False
    def signal(self, event, available):
        side=direction(event)
        self.pending[side]={'event':event, 'available':available, 'armed_at':None}
    def close(self, event, at, price):
        side=direction(event)
        self.pending.pop(side,None)
        if self.owner!=side:return None
        active=self.active
        result=replace(event,event_time=at,price=price,entry_time=active['time'],entry_price=active['price'],
                       points=(price-active['price'])*(1 if side=='BULLISH' else -1))
        self.owner='NONE'; self.active=None
        return result
    def evaluate(self, *, minute, current, reference, price, exit_boundary=False):
        accepted=[]; checks=[]
        for side,p in list(self.pending.items()):
            sign=1 if side=='BULLISH' else -1
            previous=self.previous
            gap=sign*(current.ema3_rsi-current.wma21_rsi) if current.ready else None
            prev_gap=sign*(previous['snapshot'].ema3_rsi-previous['snapshot'].wma21_rsi) if previous and previous['snapshot'].ready else None
            strength=sign*(current.wma21_rsi-reference.wma21_rsi) if current.ready and reference and reference.ready else None
            previous_strength=sign*previous['wma_change'] if previous and previous['wma_change'] is not None else None
            age=(minute-p['available']).total_seconds()/60
            consecutive=previous is not None and previous['minute']==minute-timedelta(minutes=1)
            same_boundary=exit_boundary and age == -1
            elapsed=0<=age<10 or same_boundary
            threshold=strength is not None and strength>=.75
            was_armed=p['armed_at'] is not None and minute>p['armed_at']
            persistence=(was_armed or same_boundary) and consecutive and previous_strength is not None and previous_strength>=.75 and threshold
            expansion=gap is not None and prev_gap is not None and consecutive and gap>prev_gap
            reasons=[]
            if self.locked or (minute+timedelta(minutes=1)).time()>=time(14,55):reasons.append('SESSION_CUTOFF')
            if age<0 and not same_boundary:reasons.append('WAIT_FIRST_POST_SIGNAL_MINUTE')
            elif not elapsed:reasons.append('WINDOW_EXPIRED')
            if not threshold:reasons.append('WMA_THRESHOLD_NOT_MET')
            if not persistence:reasons.append('WAIT_LATER_PERSISTENCE')
            if gap is None or gap<=0:reasons.append('GAP_NOT_POSITIVE')
            if not expansion:reasons.append('GAP_NOT_EXPANDING_OR_PREVIOUS_MINUTE_MISSING')
            if self.owner!='NONE':reasons.append('ACTIVE_TRADE_OWNER')
            check={'direction':side,'signal_timestamp':p['event'].event_time.isoformat(),
                   'signal_available_at':p['available'].isoformat(),'minute_timestamp':minute.isoformat(),
                   'decision_timestamp':(minute+timedelta(minutes=1)).isoformat(),
                   'previous_timestamp':previous['minute'].isoformat() if previous else None,
                   'previous_rsi9':previous['snapshot'].rsi9 if previous else None,
                   'previous_ema3':previous['snapshot'].ema3_rsi if previous else None,
                   'previous_wma21':previous['snapshot'].wma21_rsi if previous else None,
                   'current_rsi9':current.rsi9,'current_ema3':current.ema3_rsi,'current_wma21':current.wma21_rsi,
                   'previous_gap':prev_gap,'current_gap':gap,'gap_delta':gap-prev_gap if gap is not None and prev_gap is not None else None,
                   'directional_wma_strength':strength,'previous_directional_wma_strength':previous_strength,
                   'wma_threshold_pass':threshold,'persistence_pass':persistence,'gap_positive_pass':gap is not None and gap>0,
                   'gap_expanding_pass':expansion,'confirmation_window_pass':elapsed,
                   'ema3_continuation_delta':sign*(current.ema3_rsi-previous['snapshot'].ema3_rsi) if current.ready and previous and previous['snapshot'].ready else None,
                   'directional_alignment_diagnostic':(sign*(current.rsi9-current.ema3_rsi)>0 and sign*(current.ema3_rsi-current.wma21_rsi)>0) if current.ready else None,
                   'same_exit_boundary_confirmation':same_boundary,
                   'armed_at':p['armed_at'].isoformat() if p['armed_at'] else None,
                   'status':'ENTRY' if not reasons else 'WAIT','reasons':reasons}
            checks.append(check)
            if elapsed and threshold and p['armed_at'] is None:p['armed_at']=minute
            if not reasons:
                at=minute+timedelta(minutes=1)
                accepted.append(replace(p['event'],event_time=at,price=price,entry_time=at,entry_price=price,
                    state_before='WMA_GAP_ARMED',state_after=side+'_ACTIVE',details={'wma_gap':check,'canonical_signal':p['event'].details}))
                self.owner=side;self.active={'time':at,'price':price};del self.pending[side]
            elif age>=10 or self.locked:del self.pending[side]
        change=current.wma21_rsi-reference.wma21_rsi if current.ready and reference and reference.ready else None
        self.previous={'minute':minute,'snapshot':current,'wma_change':change}
        return accepted,checks


MODEL='HILEGA_V2_ALIGNMENT_DUAL_EXIT_REPLAY_V1'
SOURCE='V2_ALIGNMENT_DUAL_EXIT_RESEARCH'
OUTPUT_ROOT=Path('data/historical-evidence/hilega-v2-alignment-dual-exit-v1')
RULES={"version":"research-1.0.0","setup":"V1 OR completed-5m RSI9/EMA3/WMA21 ordering + positive expanding minute gap", "strength_min":0.75,"expansion_min_exclusive":0.0,"persistence":"previous/current >=0.75; later arm confirmation", "window_minutes":10,"exit":"both RSI9 and EMA3 opposite WMA21 at completed 5m close", "cutoff_IST":"14:55", "same_candle_exit_first":True,"ema10_enabled":False,"mandatory_5m_slope":False,"alternative_50_filter":False,"signal_episode":"one alternative per continuous alignment episode; no minute window reset"}
def candles(rows):
 result=[];seen=set()
 for row in rows:
  stamp=datetime.fromisoformat(row['timestamp'])
  if stamp.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
  stamp=stamp.astimezone(IST)
  if stamp in seen:raise ValueError('DUPLICATE_MINUTE')
  seen.add(stamp)
  values={k:float(row[k]) for k in ('open','high','low','close')}
  if values['high']<max(values['open'],values['close'],values['low']) or values['low']>min(values['open'],values['close']):raise ValueError('INVALID_OHLC')
  result.append(SimpleNamespace(**{**row,**values,'timestamp':stamp}))
 return sorted(result,key=lambda x:x.timestamp)
def dual_exit(side,snapshot):
 sign=1 if side=='BULLISH' else -1
 return snapshot.ready and sign*(snapshot.rsi9-snapshot.wma21_rsi)<0 and sign*(snapshot.ema3_rsi-snapshot.wma21_rsi)<0

def replay(session_date, raw_rows, warmup, metadata=None):
 TARGET=date.fromisoformat(session_date).isoformat()
 c=ExitFirstCanonical();g=WmaGapGate()
 warm=[]
 for d,rr in warmup:
  if d>=TARGET:raise ValueError('FUTURE_OR_TARGET_WARMUP')
  warm.append((d,rr))
 if not warm:raise ValueError('WARMUP_REQUIRED')
 for d,rows in sorted(warm):
  for b in aggregate_exact_5m(candles(rows),date.fromisoformat(d)):c.on_bar(b)
 if not c.bullish.previous_indicators or not c.bullish.previous_indicators.ready:raise ValueError('INDICATOR_WARMUP_NOT_READY')
 day=date.fromisoformat(TARGET);c.bullish.session=SessionState(session_date=day);c.bearish.session=BearishSessionState(session_date=day)
 for eng in [c.bullish,c.bearish]:eng.previous_indicators=None;eng.previous_bar=None
 c.trade_owner='NONE';c.session_date=day
 rows=candles(raw_rows)
 selected=[x for x in rows if x.timestamp.date()==day and '09:15'<=x.timestamp.strftime('%H:%M')<'14:55']
 expected=[datetime.combine(day,time(9,15),tzinfo=IST)+timedelta(minutes=i) for i in range(340)]
 if [x.timestamp for x in selected]!=expected:raise ValueError('INCOMPLETE_STRATEGY_MINUTES')
 cutoff=datetime.combine(day,time(14,55),tzinfo=IST)
 if not any(x.timestamp==cutoff for x in rows):raise ValueError('EXACT_1455_OPEN_REQUIRED')
 bars={b.ts:b for b in aggregate_exact_5m(selected,day,require_full_session=False)}
 setup_attempts=[];audit=[];trade_number=0;trades=[];active=None;checks=[];signals=[]; episode={"BULLISH":False,"BEARISH":False}
 for minute in selected:
  before=g.owner;exit_validation=None
  t=minute.timestamp;at=t+timedelta(minutes=1);ref=c.bullish.previous_indicators;current=copy.deepcopy(c.bullish.indicators).update(float(minute.close));events=[]
  bar=bars.get(t-timedelta(minutes=4)) if t.minute%5==4 else None
  if bar:
   dec=c.on_bar(bar)
   # Canonical RSI exits cancel its pending setup, but cannot close the
   # independent actual position before both indicators confirm.
   for e in dec.accepted_events:
    if e.event_type in EXIT_TYPES:g.pending.pop(direction(e),None)
   if g.owner!='NONE':
    new=c.bullish.previous_indicators;side=g.owner
    sign=1 if side=='BULLISH' else -1
    rsi_opposite=sign*(new.rsi9-new.wma21_rsi)<0
    ema_opposite=sign*(new.ema3_rsi-new.wma21_rsi)<0
    exit_validation={'direction':side,'rsi9':new.rsi9,'ema3':new.ema3_rsi,'wma21':new.wma21_rsi,'rsi_opposite':rsi_opposite,'ema_opposite':ema_opposite,'dual_exit_pass':dual_exit(side,new)}
    if rsi_opposite and active.get('warning_time') is None:
     active['warning_time']=at.isoformat()
    if dual_exit(side,new):
     ev=StrategyEvent('STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21' if side=='BULLISH' else 'STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21',at,None,'ACTIVE','IDLE',exit_reason='BOTH_RSI9_EMA3_OPPOSITE_WMA21')
     closed=g.close(ev,at,float(bar.close))
     if closed:
      events.append(closed)
      active['exit_indicators']={'rsi9':new.rsi9,'ema3':new.ema3_rsi,'wma21':new.wma21_rsi}
   for e in dec.accepted_events:
    if e.event_type in ENTRY_TYPES and g.owner=='NONE' and direction(e) not in g.pending:
     g.signal(e,at);setup_attempts.append({'time':at.isoformat(),'direction':direction(e),'source':'V1_CANONICAL'})
  latest=c.bullish.previous_indicators
  for side in ['BULLISH','BEARISH']:
   sign=1 if side=='BULLISH' else -1
   aligned=latest and latest.ready and sign*(latest.rsi9-latest.ema3_rsi)>0 and sign*(latest.ema3_rsi-latest.wma21_rsi)>0
   if not aligned:episode[side]=False
   prev=g.previous
   gap=sign*(current.ema3_rsi-current.wma21_rsi) if current.ready else None
   pg=sign*(prev['snapshot'].ema3_rsi-prev['snapshot'].wma21_rsi) if prev and prev['snapshot'].ready else None
   expanding=pg is not None and gap is not None and gap>pg and prev['minute']==t-timedelta(minutes=1)
   if aligned and gap is not None and gap>0 and expanding and not episode[side] and g.owner=='NONE' and side not in g.pending and at.strftime('%H:%M')<'14:55':
    episode[side]=True
    ev=StrategyEvent('ENTRY_PATH1_ROUTE_A_CROSS_RSI50_ABOVE_WMA21' if side=='BULLISH' else 'ENTRY_BEARISH_ROUTE_B_STRUCTURAL',t,'ALTERNATIVE_ALIGNMENT','IDLE','ARMED',details={'alternative':True})
    g.signal(ev,at)
    setup_attempts.append({'time':at.isoformat(),'direction':side,'source':'ALTERNATIVE_ALIGNMENT'})
    signals.append(dict(time=at.isoformat(),direction=side,rsi=latest.rsi9,ema=latest.ema3_rsi,wma=latest.wma21_rsi,current_gap=gap,previous_gap=pg,delta=gap-pg,strength=sign*(current.wma21_rsi-ref.wma21_rsi) if ref and ref.ready else None))
  entries,cc=g.evaluate(minute=t,current=current,reference=ref,price=float(minute.close),exit_boundary=bool(events));checks.extend(cc)
  for e in events:
   active.update(exit_time=at.isoformat(),exit_price=e.price,points=e.points,exit_reason=e.exit_reason or e.event_type);trades.append(active);active=None
  for e in entries:
   trade_number+=1
   assert active is None, "ENTRY_BEFORE_EXIT"
   active=dict(trade_id=f'{TARGET}-{trade_number:03d}',direction=direction(e),entry_time=at.isoformat(),entry_price=e.price,signal_time=e.details['wma_gap']['signal_available_at'],entry_checks=e.details['wma_gap'])
  audit.append({'checkpoint':at.isoformat(),'minute_timestamp':t.isoformat(),'five_minute_label':bar.ts.isoformat() if bar else None,'nifty_close':float(minute.close),'owner_before':before,'owner_after':g.owner,'indicators':{'rsi9':current.rsi9,'ema3':current.ema3_rsi,'wma21':current.wma21_rsi},'completed_5m_indicators':{'rsi9':latest.rsi9,'ema3':latest.ema3_rsi,'wma21':latest.wma21_rsi} if latest else None,'five_minute_changes':{'rsi9':latest.rsi9-ref.rsi9,'ema3':latest.ema3_rsi-ref.ema3_rsi,'wma21':latest.wma21_rsi-ref.wma21_rsi} if bar and ref and ref.ready else None,'checks':cc,'alternative_signals':[z for z in signals if z['time']==at.isoformat()],'canonical_events':[e.event_type for e in dec.accepted_events] if bar else [],'transitions':[{'event':'EXIT_CLOSED','direction':direction(e),'price':e.price,'points':e.points} for e in events]+[{'event':'ENTRY_ACTIVE','direction':direction(e),'price':e.price} for e in entries],'exit_validation':exit_validation,'active_trade':{'direction':active['direction'],'entry_time':active['entry_time'],'entry_price':active['entry_price'],'nifty_points':(float(minute.close)-active['entry_price'])*(1 if active['direction']=='BULLISH' else -1)} if active else None,'exit_warning_time':active.get('warning_time') if active else None})
  if at.strftime('%H:%M')>='14:55':g.pending.clear()
 if active:
  at=datetime.fromisoformat(TARGET+'T14:55:00+05:30');price=float(next(x.open for x in rows if x.timestamp==at))
  side=g.owner
  ev=StrategyEvent('STRUCTURAL_EXIT_RSI_CROSS_BELOW_WMA21' if side=='BULLISH' else 'STRUCTURAL_EXIT_BEARISH_RSI_CROSS_ABOVE_WMA21',at,None,'ACTIVE','IDLE',exit_reason='SESSION_CUTOFF_1455')
  closed=g.close(ev,at,price)
  assert closed is not None
  active.update(exit_time=at.isoformat(),exit_price=price,points=closed.points,exit_reason=ev.exit_reason);trades.append(active);active=None

 if active is not None:raise ValueError('UNRESOLVED_POSITION')
 for trade in trades:
  sign=1 if trade['direction']=='BULLISH' else -1
  entry=datetime.fromisoformat(trade['entry_time']);exit_at=datetime.fromisoformat(trade['exit_time'])
  available=[z for z in rows if entry<=z.timestamp<exit_at]
  trade['mfe_points']=max([0.0]+[sign*((z.high if sign==1 else z.low)-trade['entry_price']) for z in available])
  trade['giveback_points']=trade['mfe_points']-trade['points']
  trade['setup_source']='ALTERNATIVE_ALIGNMENT' if trade['entry_checks']['signal_available_at'] in {z['time'] for z in signals if z['direction']==trade['direction']} else 'V1_CANONICAL'
 gains=sum(max(0,z['points']) for z in trades);losses=sum(max(0,-z['points']) for z in trades)
 # Cutoff is explicit and occurs after all completed minute decisions.
 if trades and trades[-1]['exit_reason']=='SESSION_CUTOFF_1455':
  audit.append({'checkpoint':cutoff.isoformat(),'minute_timestamp':cutoff.isoformat(),'owner_after':'NONE','indicators':None,'checks':[],'transitions':[{'event':'EXIT_CLOSED','direction':trades[-1]['direction'],'price':trades[-1]['exit_price'],'points':trades[-1]['points'],'reason':'SESSION_CUTOFF_1455'}]})
 summary={'strategy_id':MODEL,'available':True,'signals':len(setup_attempts),'entries':len(trades),'denied':len(setup_attempts)-len(trades),'completed':len(trades),'winning_trades':sum(z['points']>0 for z in trades),'losing_trades':sum(z['points']<0 for z in trades),'breakeven_trades':sum(z['points']==0 for z in trades),'gross_points_gained':gains,'gross_points_lost':losses,'net_points':gains-losses,'gain_loss_ratio':gains/losses if losses else None,'win_rate_pct':100*sum(z['points']>0 for z in trades)/len(trades) if trades else None}
 return {'model':MODEL,'source':SOURCE,'source_id':f'{SOURCE}:{TARGET}','session_date':TARGET,'strategy_id':MODEL,'strategy_version':RULES['version'],'rules':RULES,'trades':trades,'audit':audit,'alternative_signals':signals,'setup_attempts':setup_attempts,'checks':checks,'reports':[],'report_count':len(audit),'evidence_level':'STRATEGY','ce_available':False,'audit_chain_ok':None,'audit_chain_issue':None,'manifest':metadata or {},'performance_summary':[summary],'observation_only':True,'execution_enabled':False,'forward_confirmation_eligible':False,'warning':'Reconstructed research replay; chart/live indicator parity unconfirmed. Nifty points exclude fills, fees and slippage. Separate from frozen and forward-confirmation evidence.'}

def load_session(day,root=None):
 day=date.fromisoformat(day).isoformat();path=Path(root or OUTPUT_ROOT)/(day+'.json')
 if not path.is_file():raise FileNotFoundError(f'Publish the separate V2 alignment dual-exit replay for {day} first.')
 x=json.loads(path.read_text())
 if x.get('model')!=MODEL or x.get('session_date')!=day or x.get('execution_enabled') is not False:raise ValueError('INVALID_RESEARCH_ARTIFACT')
 return x

def merge_sessions(rows,root=None):
 merged={x['session_date']:dict(x) for x in rows}
 for p in sorted(Path(root or OUTPUT_ROOT).glob('????-??-??.json')):
  day=date.fromisoformat(p.stem).isoformat()
  row=merged.setdefault(day,{'session_date':day,'source':SOURCE,'source_id':f'{SOURCE}:{day}','status':'COMPLETE','evidence_level':'STRATEGY','ce_available':False,'expiry':None,'available_sources':[]})
  row['available_sources']=list(dict.fromkeys([*row.get('available_sources',[]),SOURCE]))
 return sorted(merged.values(),key=lambda x:x['session_date'],reverse=True)
