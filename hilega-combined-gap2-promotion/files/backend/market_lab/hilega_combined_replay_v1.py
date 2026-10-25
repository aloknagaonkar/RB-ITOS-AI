"""Combined policy replay. Original legacy engine remains available separately."""
from .hilega_v2_alignment_replay_v1 import *
from .hilega_combined_policy_v1 import RULES,POLICY_ID,VERSION,PriceFrames,make_gate,advance_boundary
MODEL='HILEGA_V2_ALIGNMENT_DUAL_EXIT_REPLAY_V1'
SOURCE='BULLISH_GAP2_FULL_WMA2_REPLAY'
OUTPUT_ROOT=Path('data/historical-evidence/hilega-combined-gap2-full-wma2-v1')

def replay(session_date, raw_rows, warmup, metadata=None):
 TARGET=date.fromisoformat(session_date).isoformat()
 c=ExitFirstCanonical();tracker=PriceFrames();g=make_gate(tracker.frames)
 warm=[]
 for d,rr in warmup:
  if d>=TARGET:raise ValueError('FUTURE_OR_TARGET_WARMUP')
  warm.append((d,rr))
 if len(warm)<20:raise ValueError('TWENTY_WARMUP_SESSIONS_REQUIRED')
 for d,rows in sorted(warm):
  for b in aggregate_exact_5m(candles(rows),date.fromisoformat(d)):
   c.on_bar(b);tracker.seed(b)
 if not c.bullish.previous_indicators or not c.bullish.previous_indicators.ready:raise ValueError('INDICATOR_WARMUP_NOT_READY')
 opening_reference=capture_opening_reference(c,date.fromisoformat(TARGET))
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
  t=minute.timestamp;at=t+timedelta(minutes=1)
  bar=bars.get(t-timedelta(minutes=4)) if t.minute%5==4 else None
  if bar is None:continue
  ref=confirmation_reference(c.bullish.previous_indicators,opening_reference,t)
  result=advance_boundary(c,g,bar,ref,tracker)
  dec=result['decision'];current=result['current'];latest=current
  events=result['exits'];entries=result['entries'];cc=result['checks'];checks.extend(cc)
  setup_attempts.extend(result['setups']);signals.extend(result['signals']);exit_validation=result['exit_validation']
  if active is not None and exit_validation and exit_validation['rsi_opposite'] and active.get('warning_time') is None:active['warning_time']=at.isoformat()
  for check in cc:
   if opening_reference is not None and ref is opening_reference.snapshot:
    check['reference_bar_timestamp']=opening_reference.bar_timestamp.isoformat()
    check['reference_crosses_session']=True
  pending_switches=result['pending_switches']
  if entries:g.pending.clear()
  for e in events:
   active.update(exit_time=at.isoformat(),exit_price=e.price,points=e.points,exit_reason=e.exit_reason or e.event_type);trades.append(active);active=None
  for e in entries:
   trade_number+=1
   assert active is None, "ENTRY_BEFORE_EXIT"
   active=dict(trade_id=f'{TARGET}-{trade_number:03d}',direction=direction(e),entry_time=at.isoformat(),entry_price=e.price,signal_time=e.details['wma_gap']['signal_available_at'],entry_checks=e.details['wma_gap'])
  if decision_checkpoint(boundary=bar is not None, checks=cc, entries=entries, exits=events):
   audit.append({'policy_id':POLICY_ID,'strategy_version':VERSION,'policy_events':result['policy_events'],'price_ema_frame':result['frame'],'checkpoint':at.isoformat(),'minute_timestamp':t.isoformat(),'five_minute_label':bar.ts.isoformat() if bar else None,'nifty_close':float(minute.close),'owner_before':before,'owner_after':g.owner,'indicators':{'rsi9':current.rsi9,'ema3':current.ema3_rsi,'wma21':current.wma21_rsi},'completed_5m_indicators':{'rsi9':latest.rsi9,'ema3':latest.ema3_rsi,'wma21':latest.wma21_rsi} if latest else None,'five_minute_changes':{'rsi9':latest.rsi9-ref.rsi9,'ema3':latest.ema3_rsi-ref.ema3_rsi,'wma21':latest.wma21_rsi-ref.wma21_rsi} if bar and ref and ref.ready else None,'checks':cc,'pending_switches':pending_switches,'alternative_signals':[z for z in signals if z['time']==at.isoformat()],'canonical_events':[e.event_type for e in dec.accepted_events] if bar else [],'transitions':[{'event':'EXIT_CLOSED','direction':direction(e),'price':e.price,'points':e.points} for e in events]+[{'event':'ENTRY_ACTIVE','direction':direction(e),'price':e.price} for e in entries],'exit_validation':exit_validation,'active_trade':{'direction':active['direction'],'entry_time':active['entry_time'],'entry_price':active['entry_price'],'nifty_points':(float(minute.close)-active['entry_price'])*(1 if active['direction']=='BULLISH' else -1)} if active else None,'exit_warning_time':active.get('warning_time') if active else None})
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
 return {'model':MODEL,'source':SOURCE,'source_id':f'{SOURCE}:{TARGET}','session_date':TARGET,'strategy_id':MODEL,'strategy_version':RULES['version'],'rules':RULES,'trades':trades,'audit':audit,'alternative_signals':signals,'setup_attempts':setup_attempts,'checks':checks,'reports':[],'report_count':len(audit),'evidence_level':'STRATEGY','ce_available':False,'audit_chain_ok':None,'audit_chain_issue':None,'manifest':metadata or {},'policy_id':POLICY_ID,'policy_events':deepcopy(g.policy_events),'performance_summary':[summary],'observation_only':True,'execution_enabled':False,'forward_confirmation_eligible':False,'warning':'Reconstructed research replay; chart/live indicator parity unconfirmed. Nifty points exclude fills, fees and slippage. Separate from frozen and forward-confirmation evidence.'}

import os,tempfile,fcntl

def cache_index(roots=None):
 result={}
 # Later roots take precedence for the same date; recovery stays separate.
 for root in (CACHE_ROOTS if roots is None else roots):
  for p in sorted(Path(root).glob('????-??-??.json')):
   date.fromisoformat(p.stem);result[p.stem]=p
 return result

def source_signature(paths):
 # Read bounded files, never the entire live audit. Changes invalidate the cache.
 hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
 engine_hash=hashlib.sha256(Path(__file__).read_bytes()+Path(__file__).with_name('hilega_opening_reference_v1.py').read_bytes()+Path(__file__).with_name('hilega_combined_policy_v1.py').read_bytes()+Path(__file__).with_name('hilega_v2_alignment_replay_v1.py').read_bytes()).hexdigest()
 signature=hashlib.sha256(json.dumps({'files':hashes,'engine':engine_hash,'rules':RULES},sort_keys=True).encode()).hexdigest()
 return signature,hashes

def validate_saved(x,day):
 if x.get('model')!=MODEL or x.get('session_date')!=day or x.get('strategy_version')!=VERSION or x.get('execution_enabled') is not False:raise ValueError('INVALID_RESEARCH_ARTIFACT')
 x['reports']=[{'checkpoint':a['checkpoint']} for a in x.get('audit',[])]
 x['report_count']=len(x['reports'])
 return x

def load_session(day,root=None,cache_roots=None):
 day=date.fromisoformat(day).isoformat();output=Path(root or OUTPUT_ROOT)
 index=cache_index(cache_roots)
 if day not in index:raise FileNotFoundError(f'V2 alignment replay: local Nifty 1m candle cache missing for {day}. A listed recorded/research session is not proof of candle availability. Recover candle data before evaluating this date.')
 selected=[(d,p) for d,p in sorted(index.items()) if d<=day]
 fingerprint,hashes=source_signature([p for _,p in selected])
 artifact=output/(day+'.json')
 if artifact.is_file():
  x=json.loads(artifact.read_text())
  if (x.get('manifest') or {}).get('auto_input_signature')==fingerprint:
   return validate_saved(x,day)
 output.mkdir(parents=True,exist_ok=True)
 # Cross-process per-date lock: no duplicate replay calculations.
 with (output/(day+'.lock')).open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise ReplayBusyError(f'Replay for {day} is already calculating. Retry shortly.')
  # Recheck after acquiring lock.
  if artifact.is_file():
   x=json.loads(artifact.read_text())
   if (x.get('manifest') or {}).get('auto_input_signature')==fingerprint:return validate_saved(x,day)
  warm=[];raw=None
  for d,p in selected:
   data=json.loads(p.read_text())
   if data.get('session_date') not in (None,d):raise ValueError(f'CACHE_SESSION_DATE_MISMATCH:{p}')
   if data.get('underlying') not in (None,'NSE_INDEX|Nifty 50'):raise ValueError(f'CACHE_UNDERLYING_MISMATCH:{p}')
   rr=data.get('candles') or []
   if d==day:raw=rr
   elif rr:warm.append((d,rr))
  if not warm:raise ValueError(f'V2 alignment replay: no prior-session indicator warmup for {day}.')
  result=replay(day,raw,warm,{'source':'AUTO_LOCAL_HISTORICAL_CANDLE_REPLAY','auto_input_signature':fingerprint,'source_sha256':hashes,'warmup_first':warm[0][0],'warmup_last':warm[-1][0],'chart_parity_verified':False})
  # Preserve the previous research artifact before refresh; frozen/live data untouched.
  if artifact.is_file():
   version=hashlib.sha256(artifact.read_bytes()).hexdigest()[:16]
   history=output/'previous-research-versions';history.mkdir(exist_ok=True)
   previous=history/(day+'-'+version+'.json')
   if not previous.exists():previous.write_bytes(artifact.read_bytes())
  with tempfile.NamedTemporaryFile('w',dir=output,delete=False) as f:
   json.dump(result,f,indent=2);tmp=f.name
  os.replace(tmp,artifact)
  return validate_saved(result,day)

def merge_sessions(rows,root=None,cache_roots=None):
 merged={x['session_date']:dict(x) for x in rows};index=cache_index(cache_roots)
 # Keep the same existing date registry. Do not scan/deserialize hundreds of caches.
 for p in sorted(Path(root or OUTPUT_ROOT).glob('????-??-??.json')):
  day=date.fromisoformat(p.stem).isoformat()
  merged.setdefault(day,{'session_date':day,'source':SOURCE,'source_id':f'{SOURCE}:{day}','status':'COMPLETE','evidence_level':'STRATEGY','ce_available':False,'expiry':None,'available_sources':[]})
 for day,row in merged.items():
  if day in index:row['available_sources']=list(dict.fromkeys([*row.get('available_sources',[]),SOURCE]))
  row['alignment_candle_cache_available']=day in index
 return sorted(merged.values(),key=lambda x:x['session_date'],reverse=True)
