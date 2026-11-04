"""Read-only manual execution events for the existing decision-candle timeline."""
from datetime import datetime
from pathlib import Path
import json
ROOT=Path('data/live-observation/hilega-upstox-sandbox-v2')
STRATEGY='HILEGA_V2_ALIGNMENT_DUAL_EXIT'
def _read(path):return json.loads(path.read_text()) if path.exists() else {}
def _at(value):return datetime.fromisoformat(value.replace('Z','+00:00'))
def overlay_manual_exit_rows(rows,records,day,*,requests=None,acks=None):
 requests=_read(ROOT/'manual-exit.json').get('requests',[]) if requests is None else requests
 acks=_read(ROOT/'manual-reset-acks.json') if acks is None else acks
 by_id={r['request_id']:r for r in requests if r.get('session_date')==day and r.get('strategy_id')==STRATEGY}
 confirmations={}
 for record in records:
  p=record.get('payload') or {}
  if record.get('stage')!='DIRECTIONAL_MANUAL_EXIT_RESET' or record.get('status')!='PROCESSED' or p.get('strategy_id')!=STRATEGY:continue
  at=p.get('completed_at');rid=p.get('request_id')
  if rid and at and at[:10]==day:confirmations[rid]=(at,p)
 for rid,r in by_id.items():
  if r.get('completed_at') and rid in acks:confirmations.setdefault(rid,(r['completed_at'],{}))
 def side_for(r,p):
  side=p.get('trade_owner_before')
  if side in {'BULLISH','BEARISH'}:return side
  sides={l.get('direction') for l in r.get('legs',[])}|{l.get('direction') for l in r.get('uncertain_requests',[])}
  sides.discard(None)
  return next(iter(sides)) if len(sides)==1 and sides<={'BULLISH','BEARISH'} else None
 def event_row(rid,r,p,at,confirmed):
  side=side_for(r,p)
  if not side:return None
  origin=next((l.get('event_timestamp') for l in r.get('legs',[]) if l.get('event_timestamp')),None)
  source=next((row for row in rows.values() if row.get('bar_timestamp')==origin and row.get('strategy_id')==STRATEGY),{})
  meta=dict(request_id=rid,status='CONFIRMED' if confirmed else 'REQUESTED',execution_status=r.get('status'),requested_at=r.get('requested_at'),completed_at=r.get('completed_at'),strategy_reset_confirmed=confirmed,trade_ids=r.get('trade_ids',[]),event_only=True)
  event='MANUAL_EXIT_'+side
  return dict(session_date=day,time=at[11:16],bar_timestamp=at,decision_timestamp=at,audit_row_id='MANUAL_'+rid+('_CLOSED' if confirmed else '_REQUESTED'),strategy_id=STRATEGY,
   open=None,high=None,low=None,close=None,volume=None,rsi9=None,ema3_rsi=None,wma21_rsi=None,
   owner_before=side,owner_after='NONE' if confirmed else side,bullish_state='IDLE' if confirmed or side!='BULLISH' else 'BULLISH_ACTIVE',bearish_state='IDLE' if confirmed or side!='BEARISH' else 'BEARISH_ACTIVE',bullish_armed=False,bearish_armed=False,
   action=side+'_EXIT' if confirmed else side+'_ACTIVE',accepted_events=event if confirmed else '',suppressed_events='',note='MANUAL_EXIT_CONFIRMED' if confirmed else 'MANUAL_EXIT_REQUESTED_WAITING_FOR_CLOSURE',directional_evidence=True,audit_status='PROCESSED',manual_exit=meta,
   event_details=[dict(event_type=event,event_time=at,exit_reason='MANUAL_EXIT',price=None,points=None,entry_time=origin,entry_price=source.get('close'))] if confirmed else [])
 for rid,r in by_id.items():
  at=r.get('requested_at')
  if at and at[:10]==day:
   row=event_row(rid,r,{},at,False)
   if row:rows[at+'#MANUAL_REQUEST_'+rid]=row
 for rid,(at,p) in confirmations.items():
  r=by_id.get(rid,{})
  row=event_row(rid,r,p,at,True)
  if not row:continue
  rows[at+'#MANUAL_EXIT_'+rid]=row
  # Confirmed execution reset ends the old UI lifecycle. A fresh accepted entry
  # starts another; preserve untouched raw ownership as inspection metadata.
  for key,following in sorted(rows.items()):
   ts=following.get('bar_timestamp')
   if not ts or _at(ts)<=_at(at) or following.get('strategy_id')!=STRATEGY:continue
   events=str(following.get('accepted_events') or '')
   if any(x.startswith('ENTRY_') or x=='WMA_GAP_ENTRY' for x in events.split(',')):break
   if following.get('action') in {'BULLISH_ACTIVE','BEARISH_ACTIVE'}:
    following['manual_exit_source_state']=dict(owner_before=following.get('owner_before'),owner_after=following.get('owner_after'),action=following.get('action'))
    following.update(owner_before='NONE',owner_after='NONE',action='ARMED_INFORMATION' if following.get('bullish_armed') or following.get('bearish_armed') else 'NO_ACTION',bullish_state='IDLE',bearish_state='IDLE')
 return rows
