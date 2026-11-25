"""Upstox-specific request/response mapping. Mutation methods unconditionally disabled."""
import hashlib,json,re,math
from datetime import datetime,date
from decimal import Decimal,InvalidOperation
from zoneinfo import ZoneInfo
IST=ZoneInfo('Asia/Kolkata')
class Blocked(ValueError):pass

def stamp(v):
    try:t=datetime.fromisoformat(v)
    except (TypeError,ValueError):raise Blocked('INVALID_TIME') from None
    if t.tzinfo is None:raise Blocked('AWARE_TIME_REQUIRED')
    return t.astimezone(IST)
def positive(v):
    if isinstance(v,bool) or not isinstance(v,(str,int,float,Decimal)):raise Blocked('INVALID_POSITIVE_NUMBER')
    try:d=Decimal(str(v))
    except InvalidOperation:raise Blocked('INVALID_POSITIVE_NUMBER') from None
    if not d.is_finite() or d<=0:raise Blocked('INVALID_POSITIVE_NUMBER')
    return d
def integer(v):
    if type(v)is not int or v<=0:raise Blocked('POSITIVE_INTEGER_REQUIRED')
    return v

def draft(contract,*,request_id,side,lots,as_of,order_type='MARKET',limit_price=None,normalized_tick_rupees=None,market_protection=-1):
    if not isinstance(request_id,str) or not request_id or len(request_id)>200:raise Blocked('LOCAL_REQUEST_ID_REQUIRED')
    now=stamp(as_of);instrument=contract.get('instrument_key')
    if not isinstance(instrument,str) or not re.fullmatch(r'NSE_FO\|[0-9]+',instrument):raise Blocked('NSE_FO_INSTRUMENT_REQUIRED')
    if contract.get('underlying_key')!='NSE_INDEX|Nifty 50' or contract.get('instrument_type') not in {'CE','PE'} or contract.get('segment')!='NSE_FO':raise Blocked('NIFTY_OPTION_METADATA_REQUIRED')
    if date.fromisoformat(contract['expiry'])<now.date():raise Blocked('CONTRACT_EXPIRED')
    quantity=integer(contract['lot_size'])*integer(lots);freeze=integer(contract['freeze_quantity']);minimum=integer(contract['minimum_lot'])
    if quantity>2147483647 or quantity>freeze or quantity%minimum:raise Blocked('QUANTITY_FREEZE_OR_MINIMUM_INVALID')
    if side not in {'BUY','SELL'}:raise Blocked('SIDE_INVALID')
    body=dict(quantity=quantity,product='I',validity='DAY',price=0,tag='HILEGA-'+hashlib.sha256(request_id.encode()).hexdigest()[:32],
        instrument_token=instrument,order_type=order_type,transaction_type=side,disclosed_quantity=0,trigger_price=0,is_amo=False,slice=False)
    if order_type=='MARKET':
        if type(market_protection)is not int or market_protection not in {-1,*range(1,26)}:raise Blocked('MARKET_PROTECTION_REQUIRED')
        if limit_price is not None:raise Blocked('MARKET_DRAFT_HAS_LIMIT_PRICE')
        body['market_protection']=market_protection
    elif order_type=='LIMIT':
        value=positive(limit_price);tick=positive(normalized_tick_rupees)
        if value%tick:raise Blocked('LIMIT_PRICE_OFF_NORMALIZED_TICK')
        if not math.isfinite(float(value)):raise Blocked('LIMIT_PRICE_OUT_OF_RANGE')
        body['price']=float(value)
    else:raise Blocked('ONLY_MARKET_OR_LIMIT_DRAFT_SUPPORTED')
    return dict(model='HILEGA_DISABLED_UPSTOX_REQUEST_DRAFT_V1',request_id=request_id,created_at=now.isoformat(),
        documented_method='POST',documented_host='api-hft.upstox.com',documented_path='/v3/order/place',body=body,
        fingerprint=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        submission_enabled=False,entry_permission=False,orders_sent=False)

def order_id(v):
    if not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9-]{1,100}',v):raise Blocked('ORDER_ID_INVALID')
    return v

def place_ack(raw):
    if not isinstance(raw,dict) or raw.get('status')!='success':return dict(status='UNKNOWN_REQUIRES_RECONCILIATION',retry_allowed=False,fill_confirmed=False)
    data=raw.get('data');ids=data.get('order_ids') if isinstance(data,dict) else None
    if not isinstance(ids,list) or len(ids)!=1:return dict(status='AMBIGUOUS_OR_SPLIT_ACK_REVIEW',retry_allowed=False,fill_confirmed=False)
    try:oid=order_id(ids[0])
    except Blocked:return dict(status='INVALID_ACK_REVIEW',retry_allowed=False,fill_confirmed=False)
    return dict(status='ACKNOWLEDGED_NOT_FILLED',order_id=oid,retry_allowed=False,fill_confirmed=False)

def cancel_draft(oid):
    return dict(documented_method='DELETE',documented_host='api-hft.upstox.com',documented_path='/v3/order/cancel',
        query=dict(order_id=order_id(oid)),submission_enabled=False,orders_sent=False)

def cancel_ack(raw,expected):
    order_id(expected)
    if not isinstance(raw,dict) or raw.get('status')!='success' or not isinstance(raw.get('data'),dict) or raw['data'].get('order_id')!=expected:
        return dict(status='CANCEL_OUTCOME_UNKNOWN_RECONCILE',flat_confirmed=False,retry_allowed=False)
    return dict(status='CANCEL_ACKNOWLEDGED_RECONCILE_REQUIRED',flat_confirmed=False,retry_allowed=False)

class DisabledMutations:
    def submit(self,*a,**kw):raise Blocked('UPSTOX_PRODUCTION_SUBMISSION_DISABLED_IN_CODE')
    def cancel(self,*a,**kw):raise Blocked('UPSTOX_PRODUCTION_CANCELLATION_DISABLED_IN_CODE')
    def modify(self,*a,**kw):raise Blocked('UPSTOX_PRODUCTION_MODIFICATION_DISABLED_IN_CODE')

def match(request,snapshot,known_order_id,*,expected_account_scope,as_of):
    """Structural comparison only; caller must verify signed pinned capture first.
    Explicit ID from caller is NOT proof of strategy ownership/intent linkage.
    """
    if request.get('model')!='HILEGA_DISABLED_UPSTOX_REQUEST_DRAFT_V1' or request.get('submission_enabled') is not False:raise Blocked('DISABLED_DRAFT_REQUIRED')
    body=request['body'];fingerprint=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if request.get('fingerprint')!=fingerprint:raise Blocked('DRAFT_FINGERPRINT_INVALID')
    if snapshot.get('status')!='READ_ONLY_CAPTURED' or snapshot.get('account_scope')!=expected_account_scope or snapshot.get('account_identity_verified') is not True:raise Blocked('PINNED_ACCOUNT_CAPTURE_REQUIRED')
    now=stamp(as_of);start=stamp(snapshot['generated_at']);end=stamp(snapshot['completed_at'])
    if not start<=end<=now or (now-start).total_seconds()>30 or now.date()!=start.date():raise Blocked('CAPTURE_STALE_OR_WRONG_SESSION')
    if snapshot.get('production_execution_enabled') is not False or snapshot.get('entry_permission') is not False:raise Blocked('UNEXPECTED_EXECUTION_PERMISSION')
    oid=order_id(known_order_id);orders=[o for o in snapshot['orders'] if o['order_id']==oid]
    base=dict(production_execution_enabled=False,entry_permission=False,ownership_verified=False,retry_allowed=False,orders_sent=False)
    if not orders:return dict(base,status='ORDER_NOT_FOUND_ACCEPTANCE_UNRESOLVED')
    if len(orders)!=1:raise Blocked('DUPLICATE_ORDER_EVIDENCE')
    row=orders[0]
    if any(row.get(k)!=body[v] for k,v in [('instrument','instrument_token'),('product','product'),('side','transaction_type'),('quantity','quantity')]):raise Blocked('REQUEST_ORDER_FIELD_MISMATCH')
    if type(row.get('filled'))is not int or type(row.get('pending'))is not int or row['filled']<0 or row['pending']<0 or row['filled']+row['pending']>body['quantity']:raise Blocked('ORDER_QUANTITY_EVIDENCE_INVALID')
    if row.get('status') not in {'OPEN','PARTIAL','FILLED','CANCELLED','REJECTED'}:raise Blocked('ORDER_STATUS_UNKNOWN')
    if row['status']=='FILLED' and (row['filled']!=body['quantity'] or row['pending']):raise Blocked('COMPLETE_FILL_INCONSISTENT')
    if row['status'] in {'CANCELLED','REJECTED'} and row['pending'] or row['status']=='REJECTED' and row['filled']:raise Blocked('TERMINAL_ORDER_INCONSISTENT')
    trades=[t for t in snapshot['trades'] if t['order_id']==oid];seen=set();total=0;notional=Decimal(0)
    for t in trades:
        key=(t['order_id'],t['trade_id'])
        if key in seen:raise Blocked('DUPLICATE_EXECUTION')
        seen.add(key)
        if any(t.get(k)!=row[k] for k in ('instrument','product','side')):raise Blocked('EXECUTION_ORDER_MISMATCH')
        total+=integer(t['quantity']);notional+=positive(t['price'])*t['quantity']
    if total!=row['filled']:raise Blocked('ORDER_FILL_TOTAL_MISMATCH')
    return dict(base,status='REQUEST_FIELDS_MATCH_READ_ONLY_OWNERSHIP_UNVERIFIED',order_status=row['status'],filled_quantity=total,
        pending_quantity=row['pending'],average_fill_price=str(notional/total) if total else None,
        terminal_order=row['status'] in {'FILLED','CANCELLED','REJECTED'},flat_confirmed=False,
        note='Cancellation/entry status alone does not prove flat; ownership and all exits still require verified linkage')
