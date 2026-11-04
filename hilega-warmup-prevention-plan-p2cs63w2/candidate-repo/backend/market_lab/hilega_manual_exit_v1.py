"""Durable sandbox manual flattening. Provider evidence, never ACK==fill.
All mutations use the existing basket worker lock. No live-order client.
"""
from __future__ import annotations
import fcntl,hashlib,json,os,tempfile,uuid,math
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
IST=ZoneInfo('Asia/Kolkata')
TERMINAL={'complete','cancelled','rejected'}
ACTIVE={'REQUESTED','EXITING','VERIFYING','RECONCILIATION_REQUIRED','WAITING_FOR_STRATEGY_RESET'}

def stamp(worker):return worker.clock().isoformat()
def state_path(worker):return worker.store.path.parent/'manual-exit.json'
def read(path):return json.loads(path.read_text()) if path.exists() else {'requests':[]}
def write(path,data):
 path.parent.mkdir(parents=True,exist_ok=True)
 fd,name=tempfile.mkstemp(dir=path.parent,prefix=path.name+'.')
 try:
  with os.fdopen(fd,'w') as f:json.dump(data,f,sort_keys=True);f.flush();os.fsync(f.fileno())
  os.replace(name,path)
  parent=os.open(path.parent,os.O_RDONLY)
  try:os.fsync(parent)
  finally:os.close(parent)
 finally:
  if os.path.exists(name):os.unlink(name)
@contextmanager
def worker_lock(worker):
 worker.store.path.parent.mkdir(parents=True,exist_ok=True)
 with open(str(worker.store.path)+'.worker.lock','a') as f:
  fcntl.flock(f,fcntl.LOCK_EX)
  try:yield
  finally:fcntl.flock(f,fcntl.LOCK_UN)

def current(worker):
 requests=read(state_path(worker))['requests']
 return requests[-1] if requests else None

def request_exit(worker,*,request_id,session_date,expected_trade_ids):
 uuid.UUID(request_id)
 with worker_lock(worker):
  data=read(state_path(worker));c=worker.control.read()
  for r in data['requests']:
   if r['request_id']==request_id:return r
  if data['requests'] and data['requests'][-1]['status'] in ACTIVE:return data['requests'][-1]
  if c.get('sandbox_only') is not True or c.get('live_execution_enabled') is not False:raise ValueError('SANDBOX_ONLY_REQUIRED')
  if session_date!=c.get('session_date') or session_date!=worker.clock().date().isoformat():raise ValueError('STALE_SESSION_REFRESH_DASHBOARD')
  if not c.get('armed') or c.get('kill_switch'):raise ValueError('SANDBOX_NOT_ARMED_OR_KILLED')
  if c.get('strategy_id')!='HILEGA_V2_ALIGNMENT_DUAL_EXIT':raise ValueError('MANUAL_RESET_REQUIRES_ALIGNMENT_STRATEGY')
  opened=worker.store.open_legs();uncertain=worker.store.uncertain()
  ids=sorted({x['trade_id'] for x in opened+uncertain})
  if sorted(set(expected_trade_ids))!=ids:raise ValueError('POSITION_CHANGED_REFRESH_DASHBOARD')
  if not ids:return {'status':'NO_OPEN_ACKNOWLEDGED_LEGS','request_id':request_id}
  if any(x.get('strategy_id')!=c['strategy_id'] or x.get('session_date')!=session_date for x in opened+uncertain):raise ValueError('FOREIGN_OR_STALE_POSITION_REQUIRES_RECONCILIATION')
  r=dict(request_id=request_id,status='REQUESTED',session_date=session_date,strategy_id=c['strategy_id'],requested_at=stamp(worker),trade_ids=ids,legs=opened,uncertain_requests=uncertain,sells={},buy_cancels=[],last_error=None,prior_entries_blocked=bool(c.get('entries_blocked')),prior_failure_reason=c.get('failure_reason'),prior_failed_at=c.get('failed_at'))
  data['requests'].append(r);write(state_path(worker),data)
  return r

def order_evidence(detail,*,instrument,side,quantity,order_id=None,tag=None):
 if not isinstance(detail,dict):raise ValueError('INVALID_ORDER_EVIDENCE')
 if order_id and str(detail.get('order_id'))!=str(order_id):raise ValueError('ORDER_ID_MISMATCH')
 if tag and detail.get('tag')!=tag:raise ValueError('ORDER_TAG_MISMATCH')
 if detail.get('instrument_token')!=instrument or detail.get('transaction_type')!=side or detail.get('product')!='I':raise ValueError('ORDER_IDENTITY_MISMATCH')
 q=int(detail['quantity']);filled=int(detail['filled_quantity']);pending=int(detail['pending_quantity'])
 if q!=quantity or not 0<=filled<=q or not 0<=pending<=q-filled:raise ValueError('INVALID_ORDER_QUANTITY')
 status=str(detail['status']).lower()
 if status=='complete' and (filled!=q or pending!=0):raise ValueError('INCONSISTENT_COMPLETE_ORDER')
 price=float(detail.get('average_price') or 0)
 if not math.isfinite(price) or price<0 or (filled and price<=0):raise ValueError('MISSING_FILL_PRICE')
 return dict(order_id=str(detail['order_id']),status=status,filled=filled,pending=pending,average_price=price,terminal=status in TERMINAL)

def recover_unknown(worker,r,tr):
 for old in r['uncertain_requests']:
  rid=old['request_id']
  known=next((x for x in worker.store.rows() if x.get('request_id')==rid and x.get('status') in {'ACCEPTED','REQUEST_RESOLVED_NO_FILL'}),None)
  if known:
   if known['status']=='ACCEPTED' and old['event_type']=='ENTRY' and not any(x['trade_id']==old['trade_id'] and x['role']==old['role'] for x in r['legs']):r['legs'].append(known)
   continue
  tag='HIL5_'+rid[:32]
  # Lookup failure/not-found is not proof of rejection and never permits retry.
  detail=tr.order_details(tag=tag)
  ev=order_evidence(detail,instrument=old['contract']['instrument_key'],side=old['transaction_type'],quantity=old['quantity'],tag=tag)
  if old['event_type']=='ENTRY' and ev['terminal'] and not ev['filled']:
   worker.store.append(dict(old,status='REQUEST_RESOLVED_NO_FILL',terminal=True,broker_order_id=ev['order_id']))
   continue
  known=dict(old,status='ACCEPTED',terminal=True,broker_order_id=ev['order_id'])
  worker.store.append(known)
  if old['event_type']=='ENTRY' and not any(x['trade_id']==old['trade_id'] and x['role']==old['role'] for x in r['legs']):r['legs'].append(known)

def reconcile(worker,r,tr):
 recover_unknown(worker,r,tr)
 all_flat=True;rows=worker.store.rows();errors=[]
 for leg in r['legs']:
  try:
   key=leg['trade_id']+'|'+str(leg['role']);contract=leg['contract'];instrument=contract['instrument_key'];quantity=int(leg['quantity'])
   buy=order_evidence(tr.order_details(order_id=leg['broker_order_id']),instrument=instrument,side='BUY',quantity=quantity,order_id=leg['broker_order_id'])
   leg['confirmed_buy']=buy
   if not buy['terminal']:
    # Cancel unfilled BUY quantity; a cancel ACK is not terminal evidence.
    if buy['order_id'] not in r['buy_cancels']:
     r['buy_cancels'].append(buy['order_id']);persist(worker,r)
     try:tr.cancel_order(buy['order_id'])
     except Exception:pass # Poll actual order status, not repeat blindly.
    all_flat=False;continue
   sells=r['sells'].setdefault(key,[])
   # Reuse any previously acknowledged automatic SELL; never sell twice.
   for old in rows:
    if old.get('trade_id')==leg['trade_id'] and old.get('role')==leg['role'] and old.get('event_type')=='EXIT' and old.get('status')=='ACCEPTED' and not old.get('manual_exit_confirmed'):
     if not any(x.get('order_id')==old['broker_order_id'] for x in sells):sells.append(dict(order_id=old['broker_order_id'],quantity=int(old['quantity']),tag=None,external=True,submitted_at=old.get('timestamp',stamp(worker))))
   sold=0;cost=0;pending=False
   for sell in sells:
    detail=tr.order_details(order_id=sell.get('order_id'),tag=sell['tag'] if not sell.get('order_id') else None)
    ev=order_evidence(detail,instrument=instrument,side='SELL',quantity=sell['quantity'],order_id=sell.get('order_id'),tag=sell['tag'] if not sell.get('order_id') else None)
    if ev['filled']<sell.get('evidence',{}).get('filled',0):raise ValueError('BROKER_FILLED_QUANTITY_REGRESSED')
    sell.update(order_id=ev['order_id'],evidence=ev);sold+=ev['filled'];cost+=ev['filled']*ev['average_price'];pending=pending or not ev['terminal']
    if not ev['terminal'] and sell.get('submitted_at') and (worker.clock()-datetime.fromisoformat(sell['submitted_at'])).total_seconds()>=60 and not sell.get('cancel_requested'):
     sell['cancel_requested']=True;persist(worker,r)
     try:tr.cancel_order(ev['order_id'])
     except Exception:pass
   if sold>buy['filled']:raise ValueError('SELL_QUANTITY_EXCEEDS_FILLED_BUY')
   leg['remaining_quantity']=buy['filled']-sold;leg['confirmed_exit_price']=cost/sold if sold else None
   leg['confirmed_pnl_rupees']=cost-buy['filled']*buy['average_price'] if sold==buy['filled'] else None
   if pending:all_flat=False;continue
   remaining=buy['filled']-sold
   if remaining:
    # New attempt only after all previous SELLs are terminal with known fills.
    if len(sells)>=3:raise ValueError('EXIT_RETRY_LIMIT_REQUIRES_RECONCILIATION')
    digest=hashlib.sha256(f"{r['request_id']}|{key}|{len(sells)}".encode()).hexdigest();tag='HILM_'+digest[:32]
    sell=dict(order_id=None,quantity=remaining,tag=tag,submitted_at=stamp(worker))
    sells.append(sell);persist(worker,r) # Crash-safe intent before external mutation.
    try:sell['order_id']=tr.place_market(instrument_key=instrument,quantity=remaining,transaction_type='SELL',tag=tag)
    except Exception:r['last_error']='EXIT_SUBMISSION_UNCERTAIN_LOOKUP_BY_TAG'
    all_flat=False
   else:
    marker=hashlib.sha256(f"{r['request_id']}|{key}|flat".encode()).hexdigest()
    if not any(x.get('request_id')==marker and x.get('status')=='ACCEPTED' for x in worker.store.rows()):
     worker.store.append(dict(leg,status='ACCEPTED',event_type='EXIT',transaction_type='SELL',request_id=marker,intent_id='MANUAL_EXIT_'+r['request_id'],event_id='MANUAL_EXIT_'+r['request_id'],event_timestamp=stamp(worker),source_sequence=leg.get('source_sequence',0),broker_order_id=','.join(x['order_id'] for x in sells) or 'NO_FILLED_BUY',observed_option_price=leg['confirmed_exit_price'],exit_reason='MANUAL_EXIT',manual_exit_confirmed=True,terminal=True,timestamp=stamp(worker)))
  except Exception as exc:
   errors.append(str(exc) if isinstance(exc,ValueError) else type(exc).__name__);all_flat=False
 if worker.store.uncertain():all_flat=False
 if errors:raise ValueError(';'.join(sorted(set(errors))))
 return all_flat

def persist(worker,r):
 data=read(state_path(worker))
 for i,x in enumerate(data['requests']):
  if x['request_id']==r['request_id']:data['requests'][i]=r;break
 write(state_path(worker),data)

def pump(worker,tr):
 """Caller holds worker lock. Returns True while normal dispatch must pause."""
 r=current(worker)
 if not r or r['status']=='READY_FOR_FRESH_SIGNAL':return False
 if r.get('session_date')!=worker.clock().date().isoformat():
  r['last_error']='SESSION_CHANGED_RECONCILIATION_REQUIRED';persist(worker,r);return True
 try:
  if r['status']=='WAITING_FOR_STRATEGY_RESET':
   ack=read(worker.store.path.parent/'manual-reset-acks.json').get(r['request_id'])
   if not ack:return True
   if worker.store.open_legs() or worker.store.uncertain():raise ValueError('POSITION_CHANGED_AFTER_FLAT_CONFIRMATION')
   c=worker.control.read()
   # Clear only this captured, now proven-resolved uncertainty block.
   recoverable={'SUBMISSION_UNCERTAIN_RECONCILE_REQUIRED','UNCERTAIN_REQUEST_REQUIRES_RECONCILIATION'}
   if (r['prior_failure_reason'] in recoverable and c.get('failure_reason')==r['prior_failure_reason'] and c.get('failed_at')==r.get('prior_failed_at')):
    c.update(entries_blocked=False);c.pop('failure_reason',None);c.pop('failed_at',None);worker.control.write(c);r['prior_entries_blocked']=False;r['recovered_failure_reason']=r['prior_failure_reason']
   # All other safety blocks and kill switches remain untouched.
   if r['prior_entries_blocked'] or c.get('entries_blocked') or c.get('kill_switch'):
    r['last_error']='EXITS_CONFIRMED_SAFETY_BLOCK_REMAINS';persist(worker,r);return True
   r['status']='READY_FOR_FRESH_SIGNAL';r['ready_at']=stamp(worker);persist(worker,r);return False
  r['status']='EXITING';r['last_error']=None
  if reconcile(worker,r,tr):
   r['status']='WAITING_FOR_STRATEGY_RESET';r['completed_at']=stamp(worker)
  else:r['status']='VERIFYING'
 except Exception as exc:
  r['status']='RECONCILIATION_REQUIRED';r['last_error']=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
 persist(worker,r);return True

def service_manual_exit(worker):
 r=current(worker)
 if not r or r['status']=='READY_FOR_FRESH_SIGNAL':return False
 # Same sandbox validation as automatic execution; never use a live client.
 from .hilega_upstox_sandbox_basket_v2 import SandboxConfig,BasketTransport,strategy
 c=worker.control.read()
 if c.get('strategy_id')!=r['strategy_id'] or strategy(worker.env)!=r['strategy_id'] or c.get('kill_switch') or c.get('sandbox_only') is not True or c.get('live_execution_enabled') is not False:
  r['last_error']='CONTROL_OR_STRATEGY_CHANGED_RECONCILIATION_REQUIRED';persist(worker,r);return True
 cfg=SandboxConfig.from_env(worker.env)
 try:cfg.assert_ready('SANDBOX_ONLY')
 except Exception:
  r['last_error']='SANDBOX_CONFIGURATION_NOT_READY';persist(worker,r);return True
 tr=worker.transport or BasketTransport(cfg.analytics_token,cfg.sandbox_token)
 try:return pump(worker,tr)
 finally:
  if worker.transport is None:tr.close()

def suppress_intent(worker,intent):
 data=read(state_path(worker));requests=data['requests']
 if not requests:return False
 last=requests[-1];reason=None
 if last['status'] in ACTIVE:return True # Defer, never mark fresh entries consumed while closing.
 if last['status']!='READY_FOR_FRESH_SIGNAL':return True
 closed={t for r in requests if r.get('completed_at') for t in r['trade_ids']}
 if intent['trade_id'] in closed:reason='MANUALLY_CLOSED_TRADE'
 elif intent['event_type']=='ENTRY' and datetime.fromisoformat(intent['event_timestamp'])<=datetime.fromisoformat(last['completed_at']):reason='STALE_PRE_MANUAL_EXIT_SIGNAL'
 if not reason:return False
 worker.store.append(dict(intent,status='SKIPPED_MANUAL_EXIT',terminal=True,reason=reason))
 return True

# The public CLI only enqueues durable requests; the existing worker executes them.
def accepted_order_count(worker):
 day=worker.control.read().get('session_date')
 base=sum(r.get('status')=='ACCEPTED' and r.get('session_date')==day and not r.get('manual_exit_confirmed') for r in worker.store.rows())
 known={x['order_id'] for r in read(state_path(worker))['requests'] if r['session_date']==day for xs in r['sells'].values() for x in xs if x.get('order_id') and not x.get('external')}
 return base+len(known)

def main():
 import argparse
 from .hilega_upstox_sandbox_basket_v2 import BasketWorker
 p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True);g.add_argument('--exit-all',action='store_true');g.add_argument('--status',action='store_true');g.add_argument('--check-provider',action='store_true');p.add_argument('--confirm');a=p.parse_args();w=BasketWorker()
 if a.exit_all:
  if a.confirm!='EXIT_ALL_SANDBOX_LEGS':raise ValueError('EXIT_ALL_SANDBOX_LEGS required')
  c=w.control.read();ids=sorted({r['trade_id'] for r in w.store.open_legs()+w.store.uncertain()})
  result=request_exit(w,request_id=str(uuid.uuid4()),session_date=c.get('session_date'),expected_trade_ids=ids)
 elif a.check_provider:
  from .hilega_upstox_sandbox_basket_v2 import SandboxConfig,BasketTransport
  cfg=SandboxConfig.from_env(w.env);cfg.assert_ready('SANDBOX_ONLY')
  day=w.clock().date().isoformat();entries=[x for x in w.store.rows() if x.get('status')=='ACCEPTED' and x.get('event_type')=='ENTRY' and x.get('session_date')==day]
  if not entries:result={'status':'NO_CURRENT_SESSION_ORDER_TO_VERIFY','sandbox_only':True}
  else:
   tr=BasketTransport(cfg.analytics_token,cfg.sandbox_token)
   try:
    x=entries[-1];ev=order_evidence(tr.order_details(order_id=x['broker_order_id']),instrument=x['contract']['instrument_key'],side='BUY',quantity=x['quantity'],order_id=x['broker_order_id']);result={'status':'ORDER_DETAILS_VERIFIED','evidence':ev,'sandbox_only':True,'order_sent':False}
   finally:tr.close()
 else:result=current(w) or {'status':'NO_MANUAL_EXIT_REQUEST'}
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
