"""Pinned-account Upstox read-only adapter. No order mutations or ledger writes.

API transport is the existing fixed-endpoint GET-only Client. The offline ledger
is deliberately not imported; live snapshots are never relabelled as fixtures.
"""
from __future__ import annotations
import hashlib,hmac,json,os,re,secrets,stat,uuid
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo
from .hilega_production_broker_observation_v1 import Client,write_snapshot

MODEL='HILEGA_PRODUCTION_ACCOUNT_ADAPTER_V1'
PIN_MODEL='HILEGA_UPSTOX_ACCOUNT_PIN_V1'
LIVE='LIVE_READ_ONLY_ACCOUNT_PINNED'
IST=ZoneInfo('Asia/Kolkata')
ACTIVE={'validation pending','modify pending','trigger pending','put order req received',
        'modify after market order req received','open','modify validation pending',
        'after market order req received','modified','not cancelled','cancel pending',
        'open pending','not modified'}
TERMINAL={'complete':'FILLED','cancelled':'CANCELLED','cancelled after market order':'CANCELLED','rejected':'REJECTED'}

class AdapterBlocked(ValueError):pass

def utcnow():return datetime.now(timezone.utc)
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def identifier(v):
    if not isinstance(v,str) or not v or len(v)>200 or v.strip()!=v or any(ord(c)<32 for c in v):raise AdapterBlocked('IDENTIFIER_MISSING_OR_INVALID')
    return v

def intqty(v,*,signed=False):
    if type(v) is not int or not signed and v<0:raise AdapterBlocked('QUANTITY_MISSING_OR_INVALID')
    return v

def positive_price(v):
    if isinstance(v,bool) or not isinstance(v,(str,int,float)):raise AdapterBlocked('FILL_PRICE_MISSING_OR_INVALID')
    try:p=Decimal(str(v))
    except InvalidOperation:raise AdapterBlocked('FILL_PRICE_MISSING_OR_INVALID') from None
    if not p.is_finite() or p<=0:raise AdapterBlocked('FILL_PRICE_MISSING_OR_INVALID')
    return str(p.normalize())

def aware(v):
    try:t=datetime.fromisoformat(v)
    except (TypeError,ValueError):raise AdapterBlocked('TIMESTAMP_MISSING_OR_INVALID') from None
    if t.tzinfo is None:raise AdapterBlocked('AWARE_TIMESTAMP_REQUIRED')
    return t

def day(t):return t.astimezone(IST).date().isoformat()
def broker_time(v):
    if not isinstance(v,str) or not re.search(r'\d{2}:\d{2}:\d{2}',v):raise AdapterBlocked('BROKER_TIMESTAMP_MISSING_OR_INVALID')
    try:t=datetime.fromisoformat(v)
    except ValueError:
        try:t=datetime.strptime(v,'%d-%b-%Y %H:%M:%S')
        except ValueError:raise AdapterBlocked('BROKER_TIMESTAMP_MISSING_OR_INVALID') from None
    # Upstox examples use exchange-local timestamps without an offset.
    if t.tzinfo is None:t=t.replace(tzinfo=IST)
    return t.astimezone(timezone.utc)

def profile_id(raw):
    data=response_data(raw,'profile',dict)
    if data.get('broker')!='UPSTOX':raise AdapterBlocked('UNEXPECTED_BROKER')
    if data.get('is_active') is not True:raise AdapterBlocked('BROKER_ACCOUNT_NOT_CONFIRMED_ACTIVE')
    value=data.get('user_id')
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{2,100}',value):raise AdapterBlocked('PROFILE_ACCOUNT_ID_MISSING_OR_INVALID')
    return value

def response_data(raw,name,kind):
    if not isinstance(raw,dict) or raw.get('status')!='success':
        code=raw.get('error') if isinstance(raw,dict) else None
        provider=raw.get('provider_code') if isinstance(raw,dict) else None
        safe=code if isinstance(code,str) and (re.fullmatch(r'HTTP_[0-9]{3}',code) or code in {'NETWORK_OR_TIMEOUT','INVALID_JSON','RESPONSE_TOO_LARGE'}) else 'PROVIDER_ERROR'
        if isinstance(provider,str) and re.fullmatch(r'(UDAPI[0-9]{1,12}|CLOUDFLARE_1010)',provider):safe+='_'+provider
        raise AdapterBlocked(name.upper()+'_'+safe)
    if not isinstance(raw.get('data'),kind):raise AdapterBlocked(name.upper()+'_RESPONSE_SCHEMA_INVALID')
    return raw['data']

def account_scope(key,user_id):
    return 'UPSTOX:'+hmac.new(bytes.fromhex(key),('UPSTOX|'+user_id).encode(),hashlib.sha256).hexdigest()

def enroll(path,profile,expected_user_id,*,at):
    """Caller must obtain expected ID privately from the operator, never from args."""
    at=aware(at).isoformat();uid=profile_id(profile)
    if not isinstance(expected_user_id,str) or not hmac.compare_digest(uid.encode(),expected_user_id.encode()):raise AdapterBlocked('EXPECTED_ACCOUNT_DOES_NOT_MATCH_PROFILE')
    p=Path(path);p.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
    parent=p.parent.stat()
    if parent.st_uid!=os.getuid() or stat.S_IMODE(parent.st_mode)&0o077:raise AdapterBlocked('PIN_DIRECTORY_MUST_BE_PRIVATE')
    key=secrets.token_hex(32)
    pin=dict(model=PIN_MODEL,broker='UPSTOX',scope=account_scope(key,uid),key=key,approved_at=at)
    try:fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    except FileExistsError:raise AdapterBlocked('ACCOUNT_PIN_EXISTS_NO_OVERWRITE') from None
    with os.fdopen(fd,'w') as f:json.dump(pin,f);f.flush();os.fsync(f.fileno())
    return pin

def read_pin(path):
    p=Path(path)
    try:
        parent=p.parent.stat()
        if parent.st_uid!=os.getuid() or stat.S_IMODE(parent.st_mode)&0o077:raise AdapterBlocked('PIN_DIRECTORY_MUST_BE_PRIVATE')
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'r') as f:
            st=os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)&0o077 or st.st_size>4096:raise AdapterBlocked('PIN_FILE_MUST_BE_PRIVATE_REGULAR_FILE')
            pin=json.load(f)
        if not isinstance(pin,dict) or pin.get('model')!=PIN_MODEL or pin.get('broker')!='UPSTOX':raise AdapterBlocked('ACCOUNT_PIN_INVALID')
        if not isinstance(pin.get('key'),str) or not re.fullmatch(r'[0-9a-f]{64}',pin['key']):raise AdapterBlocked('ACCOUNT_PIN_INVALID')
        if not isinstance(pin.get('scope'),str) or not re.fullmatch(r'UPSTOX:[0-9a-f]{64}',pin['scope']):raise AdapterBlocked('ACCOUNT_PIN_INVALID')
        aware(pin.get('approved_at'));return pin
    except AdapterBlocked:raise
    except (OSError,ValueError,TypeError):raise AdapterBlocked('ACCOUNT_PIN_UNAVAILABLE_OR_INVALID') from None

def matches(profile,pin):
    uid=profile_id(profile)
    if not hmac.compare_digest(account_scope(pin['key'],uid),pin['scope']):raise AdapterBlocked('BROKER_ACCOUNT_MISMATCH')
    return uid

def normalise(raw_orders,raw_trades,raw_positions,*,observed_at):
    observed=aware(observed_at);orders={};trades={};positions={}
    for o in response_data(raw_orders,'orders',list):
        if not isinstance(o,dict):raise AdapterBlocked('ORDER_SCHEMA_INVALID')
        oid=identifier(o.get('order_id'))
        if oid in orders:raise AdapterBlocked('DUPLICATE_ORDER_ID')
        instrument=identifier(o.get('instrument_token'));product=identifier(o.get('product'));side=o.get('transaction_type')
        if side not in {'BUY','SELL'}:raise AdapterBlocked('ORDER_SIDE_INVALID')
        q=intqty(o.get('quantity'));filled=intqty(o.get('filled_quantity'));pending=intqty(o.get('pending_quantity'))
        if q<=0 or filled+pending>q:raise AdapterBlocked('ORDER_QUANTITIES_INCONSISTENT')
        source=o.get('status')
        if not isinstance(source,str):raise AdapterBlocked('ORDER_STATUS_MISSING_OR_UNKNOWN')
        source=source.strip().lower()
        if source in TERMINAL:state=TERMINAL[source]
        elif source in ACTIVE:state='PARTIAL' if filled else 'OPEN'
        else:raise AdapterBlocked('ORDER_STATUS_MISSING_OR_UNKNOWN')
        if state=='FILLED' and (filled!=q or pending!=0):raise AdapterBlocked('COMPLETE_ORDER_QUANTITIES_INCONSISTENT')
        if state in {'CANCELLED','REJECTED'} and pending!=0:raise AdapterBlocked('TERMINAL_ORDER_PENDING_QUANTITY_REQUIRES_REVIEW')
        if state=='REJECTED' and filled:raise AdapterBlocked('REJECTED_ORDER_HAS_FILLS')
        stamp=broker_time(o.get('order_timestamp'))
        if day(stamp)!=day(observed) or stamp>observed:raise AdapterBlocked('ORDER_TIME_OUTSIDE_SESSION')
        orders[oid]=dict(order_id=oid,instrument=instrument,product=product,side=side,quantity=q,filled=filled,pending=pending,
                         status=state,source_status=source,placed_at=stamp.isoformat())
    for t in response_data(raw_trades,'trades',list):
        if not isinstance(t,dict):raise AdapterBlocked('TRADE_SCHEMA_INVALID')
        oid=identifier(t.get('order_id'));tid=identifier(t.get('trade_id'));q=intqty(t.get('quantity'))
        if q<=0:raise AdapterBlocked('ZERO_QUANTITY_TRADE')
        order=orders.get(oid)
        if not order:raise AdapterBlocked('TRADE_ORDER_NOT_IN_SNAPSHOT')
        if any(t.get(a)!=order[b] for a,b in [('instrument_token','instrument'),('product','product'),('transaction_type','side')]):raise AdapterBlocked('TRADE_ORDER_IDENTITY_MISMATCH')
        stamp=broker_time(t.get('exchange_timestamp'))
        if day(stamp)!=day(observed) or stamp>observed or stamp<aware(order['placed_at']):raise AdapterBlocked('TRADE_TIME_OUTSIDE_ORDER_SESSION')
        fill=dict(order_id=oid,trade_id=tid,instrument=order['instrument'],product=order['product'],side=order['side'],
                  quantity=q,price=positive_price(t.get('average_price')),filled_at=stamp.isoformat())
        key=(oid,tid)
        if key in trades and trades[key]!=fill:raise AdapterBlocked('DUPLICATE_TRADE_CONFLICT')
        trades[key]=fill
    for p in response_data(raw_positions,'positions',list):
        if not isinstance(p,dict):raise AdapterBlocked('POSITION_SCHEMA_INVALID')
        key=(identifier(p.get('instrument_token')),identifier(p.get('product')))
        if key in positions:raise AdapterBlocked('DUPLICATE_POSITION_KEY')
        positions[key]=dict(instrument=key[0],product=key[1],quantity=intqty(p.get('quantity'),signed=True))
    issues=[]
    for oid,o in orders.items():
        if sum(t['quantity'] for (k,_),t in trades.items() if k==oid)!=o['filled']:issues.append('ORDER_TRADE_FILL_TOTAL_MISMATCH')
    # No ownership map exists for live orders yet. Never infer it from a symbol/tag.
    if orders:issues.append('BROKER_ORDERS_NOT_MAPPED_TO_STRATEGY')
    if any(p['quantity']!=0 for p in positions.values()):issues.append('BROKER_EXPOSURE_NOT_MAPPED_TO_STRATEGY')
    return dict(orders=list(orders.values()),trades=list(trades.values()),positions=list(positions.values()),
                diagnostics=dict(status='REVIEW_REQUIRED' if issues else 'EMPTY_ACCOUNT_SNAPSHOT_ONLY',issues=sorted(set(issues)),
                    owned_order_count=0,unmapped_order_count=len(orders),strategy_ownership_verified=False),
                account_position_rows_complete=True,position_fill_linkage_verified=False,
                timestamp_basis='EXPLICIT_OFFSET_OR_EXCHANGE_LOCAL_IST')

def sign(report,pin):
    return hmac.new(bytes.fromhex(pin['key']),canonical(report),hashlib.sha256).hexdigest()

def capture(client,pin,*,clock=utcnow):
    if type(client) is not Client:raise AdapterBlocked('FIXED_GET_ONLY_CLIENT_REQUIRED')
    start=clock();start_text=aware(start.isoformat()).isoformat()
    # Failure snapshots intentionally contain no old balances/positions.
    base=dict(model=MODEL,evidence_mode=LIVE,generated_at=start_text,session_date=day(start),
              account_scope=pin['scope'],snapshot_id=uuid.uuid4().hex,production_execution_enabled=False,
              orders_sent=False,entry_permission=False,source_atomic=False,live_pnl=None)
    try:
        first=client.get('profile');matches(first,pin)
        responses={}
        for name in ('orders','trades','positions'):
            raw=client.get(name);response_data(raw,name,list);responses[name]=raw
        last=client.get('profile');matches(last,pin)
        end=clock();elapsed=(end-start).total_seconds()
        if not 0<=elapsed<=30 or day(end)!=day(start):raise AdapterBlocked('CAPTURE_WINDOW_TOO_LONG_OR_SESSION_CHANGED')
        # Use sweep start as conservative freshness boundary. Data can arrive later
        # within the documented 30-second sweep; timestamps are checked against end.
        value=normalise(responses['orders'],responses['trades'],responses['positions'],observed_at=end.isoformat())
        base.update(status='READ_ONLY_CAPTURED',completed_at=end.isoformat(),account_identity_verified=True,
                    profile_verified_before_and_after=True,**value)
    except AdapterBlocked as exc:
        base.update(status='BLOCKED',reason=str(exc),account_identity_verified=False,positions=None,orders=None,trades=None)
    except Exception:
        base.update(status='BLOCKED',reason='ADAPTER_EVIDENCE_UNAVAILABLE',account_identity_verified=False,positions=None,orders=None,trades=None)
    base['signature']=sign(base,pin);return base

def verify(report,pin,*,as_of):
    """Local authenticity/freshness check, not an order-placement permission."""
    if not isinstance(report,dict) or report.get('model')!=MODEL or report.get('evidence_mode')!=LIVE:raise AdapterBlocked('LIVE_PINNED_EVIDENCE_REQUIRED')
    payload=dict(report);signature=payload.pop('signature',None)
    if not isinstance(signature,str) or not hmac.compare_digest(sign(payload,pin),signature):raise AdapterBlocked('SNAPSHOT_SIGNATURE_INVALID')
    if report.get('account_scope')!=pin['scope']:raise AdapterBlocked('SNAPSHOT_ACCOUNT_SCOPE_MISMATCH')
    if report.get('production_execution_enabled') is not False or report.get('entry_permission') is not False or report.get('orders_sent') is not False:raise AdapterBlocked('UNEXPECTED_EXECUTION_PERMISSION')
    start=aware(report.get('generated_at'));current=aware(as_of)
    if not 0<=(current-start).total_seconds()<=30 or day(current)!=report.get('session_date'):raise AdapterBlocked('SNAPSHOT_STALE_OR_FUTURE')
    if report.get('status')!='READ_ONLY_CAPTURED' or report.get('account_identity_verified') is not True:raise AdapterBlocked('SNAPSHOT_BLOCKED_OR_IDENTITY_UNVERIFIED')
    end=aware(report.get('completed_at'))
    if not start<=end<=current or (end-start).total_seconds()>30:raise AdapterBlocked('SNAPSHOT_CAPTURE_TIME_INVALID')
    return dict(status='IDENTITY_AND_READ_ONLY_EVIDENCE_VERIFIED',entry_permission=False,
                strategy_ownership_verified=False,production_execution_enabled=False,
                diagnostics=report['diagnostics'])

def save_capture(report,path,pin_path):
    if Path(path).resolve()==Path(pin_path).resolve():raise AdapterBlocked('SNAPSHOT_CANNOT_OVERWRITE_PIN')
    write_snapshot(report,Path(path))
