"""Causal completed-five-minute research. No broker or production writes."""
from datetime import date,datetime,time,timedelta
from market_lab import hilega_v2_alignment_replay_v1 as b

def values(s):
 return dict(rsi9=s.rsi9,ema3=s.ema3_rsi,wma21=s.wma21_rsi) if s and s.ready else None

def check(side,previous,current):
 sign=1 if side=='BULLISH' else -1
 p,n=values(previous),values(current)
 if not p or not n:return dict(available=False,previous=p,current=n)
 slopes={k:n[k]-p[k] for k in n};gap=sign*(n['ema3']-n['wma21']);pg=sign*(p['ema3']-p['wma21'])
 return dict(available=True,previous=p,current=n,slopes=slopes,current_gap=gap,previous_gap=pg,gap_delta=gap-pg,
 alignment=sign*(n['rsi9']-n['ema3'])>0 and gap>0,gap_positive=gap>0,gap_expanding=gap>pg,
 strength=sign*slopes['wma21'],entry_wma_slope=sign*slopes['wma21']>0,
 exit_all_slopes=all(sign*d<0 for d in slopes.values()),dual_exit=b.dual_exit(side,current))

def replay(day,raw,warmup,metadata=None,*,slope_exit=True,strength_min=0):
 c=b.ExitFirstCanonical();warm_last=None
 for d,rr in sorted(warmup):
  if d>=day:raise ValueError('FUTURE_WARMUP')
  for bar in b.aggregate_exact_5m(b.candles(rr),date.fromisoformat(d)):c.on_bar(bar)
 warm_last=c.bullish.previous_indicators
 if not warm_last or not warm_last.ready:raise ValueError('WARMUP_REQUIRED')
 dt=date.fromisoformat(day);c.bullish.session=b.SessionState(session_date=dt);c.bearish.session=b.BearishSessionState(session_date=dt)
 for e in (c.bullish,c.bearish):e.previous_indicators=None;e.previous_bar=None
 c.trade_owner='NONE';c.session_date=dt
 rows=b.candles(raw);selected=[x for x in rows if x.timestamp.date()==dt and time(9,15)<=x.timestamp.time()<time(14,55)]
 expected=[datetime.combine(dt,time(9,15),tzinfo=b.IST)+timedelta(minutes=i) for i in range(340)]
 if [x.timestamp for x in selected]!=expected:raise ValueError('INCOMPLETE_STRATEGY_MINUTES')
 cutoff=datetime.combine(dt,time(14,55),tzinfo=b.IST);cutoff_rows=[x for x in rows if x.timestamp==cutoff]
 if not cutoff_rows:raise ValueError('EXACT_1455_OPEN_REQUIRED')
 bars=b.aggregate_exact_5m(selected,dt,require_full_session=False)
 active=None;trades=[];audit=[];checks=[];attempts=[];previous=warm_last;episode={'BULLISH':False,'BEARISH':False}
 def close(at,price,reason,validation):
  nonlocal active
  sign=1 if active['direction']=='BULLISH' else -1
  active.update(exit_time=at.isoformat(),exit_price=price,points=sign*(price-active['entry_price']),exit_reason=reason,exit_checks=validation)
  trades.append(active);active=None
 for bar in bars:
  at=bar.ts+timedelta(minutes=5);dec=c.on_bar(bar);current=c.bullish.previous_indicators
  both={s:check(s,previous,current) for s in episode};transitions=[];exit_check=None
  before=active['direction'] if active else 'NONE'
  if active:
   exit_check=both[active['direction']]
   if at>=cutoff:
    close(cutoff,float(cutoff_rows[0].open),'SESSION_CUTOFF_1455',exit_check);transitions.append('EXIT_CUTOFF')
   elif exit_check.get('dual_exit') and (not slope_exit or exit_check.get('exit_all_slopes')):
    close(at,float(bar.close),'DUAL_EXIT_ALL_THREE_SLOPES' if slope_exit else 'DUAL_EXIT',exit_check);transitions.append('EXIT_CLOSED')
  canonical={b.direction(e) for e in dec.accepted_events if e.event_type in b.ENTRY_TYPES}
  for side,q in both.items():
   if not q.get('alignment'):episode[side]=False
   alternative=q.get('alignment') and q.get('gap_expanding') and not episode[side]
   signal=side in canonical or alternative
   reasons=[]
   if not q.get('available'):reasons.append('PREVIOUS_INDICATOR_UNAVAILABLE')
   if not q.get('alignment'):reasons.append('ALIGNMENT_NOT_MET')
   if not q.get('gap_positive'):reasons.append('GAP_NOT_POSITIVE')
   if not q.get('gap_expanding'):reasons.append('GAP_NOT_EXPANDING')
   if not q.get('entry_wma_slope') or q.get('strength',-1)<strength_min:reasons.append('WMA_SLOPE_OR_STRENGTH_NOT_MET')
   if active:reasons.append('ACTIVE_OWNER')
   if at>=cutoff:reasons.append('SESSION_CUTOFF')
   if not signal:reasons.append('NO_FRESH_SETUP')
   audit_check=dict(direction=side,decision_timestamp=at.isoformat(),previous_timestamp=(bar.ts-timedelta(minutes=5)).isoformat() if previous is not warm_last else 'PRIOR_SESSION_LAST_COMPLETED_BAR',current_bar_timestamp=bar.ts.isoformat(),signal=bool(signal),status='ENTRY' if not reasons else 'WAIT',reasons=reasons,**q)
   checks.append(audit_check)
   if signal:attempts.append(dict(time=at.isoformat(),direction=side,source='V1_CANONICAL' if side in canonical else 'ALTERNATIVE_ALIGNMENT'))
   # Rejected setup is not carried into a one-minute confirmation window.
   # Alignment episode is consumed on first signal; a fresh canonical setup can retry.
   if alternative:episode[side]=True
   if not reasons:
    assert active is None
    active=dict(trade_id=f'{day}-{len(trades)+1:03d}',direction=side,entry_time=at.isoformat(),entry_price=float(bar.close),signal_time=at.isoformat(),entry_checks=audit_check,setup_source='V1_CANONICAL' if side in canonical else 'ALTERNATIVE_ALIGNMENT')
    transitions.append('ENTRY_'+side)
  audit.append(dict(checkpoint=at.isoformat(),five_minute_label=bar.ts.isoformat(),owner_before=before,owner_after=active['direction'] if active else 'NONE',previous_indicators=values(previous),current_indicators=values(current),checks=checks[-2:],exit_validation=exit_check,transitions=transitions))
  previous=current
 assert active is None
 for t in trades:
  sign=1 if t['direction']=='BULLISH' else -1;entry=datetime.fromisoformat(t['entry_time']);exit_at=datetime.fromisoformat(t['exit_time'])
  t['mfe_points']=max([0]+[sign*((z.high if sign==1 else z.low)-t['entry_price']) for z in rows if entry<=z.timestamp<exit_at]);t['giveback_points']=t['mfe_points']-t['points']
 return dict(model='HILEGA_V2_STRICT5M_RESEARCH',session_date=day,trades=trades,audit=audit,checks=checks,setup_attempts=attempts,execution_enabled=False,metadata=metadata or {},rules=dict(timeframe='completed 5m',entry='V1 OR fresh alignment episode; ordering AND positive expanding gap AND directional WMA slope',strength_min=strength_min,exit='dual indicator exit AND all three opposite slopes' if slope_exit else 'dual indicator exit',cutoff='14:55 unconditional',same_boundary='exit first',previous='preceding completed 5m; first bar uses prior session last completed bar'))
