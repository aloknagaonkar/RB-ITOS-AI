"""Pure signed-cash checks extracted from the installed shadow gate; no book. """
import hashlib,hmac,json,os,sqlite3

from contextlib import contextmanager

from datetime import datetime

from decimal import Decimal,InvalidOperation,ROUND_DOWN,ROUND_UP

from pathlib import Path

from zoneinfo import ZoneInfo

IST=ZoneInfo('Asia/Kolkata')

class Blocked(ValueError):pass

def encode(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)

def stamp(value):
    try:t=datetime.fromisoformat(value)
    except (ValueError,TypeError):raise Blocked('INVALID_TIME') from None
    if t.tzinfo is None:raise Blocked('AWARE_TIME_REQUIRED')
    return t.astimezone(IST)

def decimal(value):
    if isinstance(value,bool) or not isinstance(value,(int,float,str,Decimal)):raise Blocked('INVALID_AMOUNT')
    try:d=Decimal(str(value))
    except InvalidOperation:raise Blocked('INVALID_AMOUNT') from None
    if not d.is_finite() or d<0:raise Blocked('INVALID_AMOUNT')
    return d

def cents(value,up=False):return int((decimal(value)*100).to_integral_value(rounding=ROUND_UP if up else ROUND_DOWN))

def amount(value):return str((Decimal(value)/100).quantize(Decimal('.01')))

def identity(v):
    if not isinstance(v,str) or not 1<=len(v)<=200 or any(ord(c)<32 for c in v):raise Blocked('INVALID_ID')
    return v

def verify_capture(record,pin,*,as_of):
    from signature_checks import sign
    if not isinstance(record,dict):raise Blocked('CAPTURE_REQUIRED')
    data=dict(record);signature=data.pop('signature',None)
    if not isinstance(signature,str) or not hmac.compare_digest(sign(data,pin),signature):raise Blocked('CAPTURE_SIGNATURE_INVALID')
    if data.get('model')!='HILEGA_READ_ONLY_CASH_OBSERVATION_V1' or data.get('evidence_mode')!='LIVE_READ_ONLY_ACCOUNT_PINNED':raise Blocked('PINNED_CASH_CAPTURE_REQUIRED')
    if data.get('account_scope')!=pin['scope'] or data.get('account_identity_verified') is not True:raise Blocked('ACCOUNT_SCOPE_UNVERIFIED')
    if data.get('status')!='READ_ONLY_CAPTURED':raise Blocked('CASH_CAPTURE_FAILED')
    if data.get('account_position_rows_complete') is not True:raise Blocked('INCOMPLETE_ACCOUNT_EVIDENCE')
    if any(data.get(k) is not False for k in ('production_execution_enabled','orders_sent','entry_permission')):raise Blocked('READ_ONLY_FLAGS_REQUIRED')
    now=stamp(as_of);start=stamp(data.get('started_at'));end=stamp(data.get('completed_at'))
    if not 0<=(end-start).total_seconds()<=30 or not 0<=(now-end).total_seconds()<=30:raise Blocked('CAPTURE_STALE_FUTURE_OR_SLOW')
    if start.date()!=now.date() or end.date()!=now.date() or data.get('session_date')!=now.date().isoformat():raise Blocked('WRONG_SESSION')
    identity(data.get('snapshot_id'))
    before=data.get('funds_before');after=data.get('funds_after')
    if not isinstance(before,dict) or not isinstance(after,dict):raise Blocked('FUNDS_REQUIRED')
    field='data.available_to_trade.cash_available_to_trade.total'
    if before.get('field')!=field or after.get('field')!=field:raise Blocked('NET_CASH_FIELD_REQUIRED')
    cash=cents(after.get('cash_available_to_trade'))
    # Capture coherence does not establish order-level debit attribution.
    drift=before!=after or data.get('funds_changed_during_capture') is not False
    reasons=[]
    if drift:reasons.append('FUNDS_CHANGED_DURING_CAPTURE')
    for key in ('orders','trades','positions'):
        if not isinstance(data.get(key),list):raise Blocked('ACCOUNT_EVIDENCE_REQUIRED')
    if data['orders'] or data['trades']:reasons.append('ACCOUNT_ORDER_OR_FILL_ACTIVITY_OWNERSHIP_UNVERIFIED')
    for p in data['positions']:
        if not isinstance(p,dict) or type(p.get('quantity'))is not int:raise Blocked('POSITION_SCHEMA_INVALID')
        if p['quantity']!=0:reasons.append('ACCOUNT_EXPOSURE_OWNERSHIP_UNVERIFIED')
    diagnostics=data.get('diagnostics')
    if not isinstance(diagnostics,dict) or not isinstance(diagnostics.get('issues'),list):raise Blocked('DIAGNOSTICS_REQUIRED')
    if diagnostics['issues']:reasons.append('ACCOUNT_EVIDENCE_DIAGNOSTICS_REQUIRE_REVIEW')
    return dict(snapshot_id=data['snapshot_id'],observed_at=end.isoformat(),session_date=data['session_date'],cash_cents=cash,
        half_cash_cap_cents=cash//2,reasons=sorted(set(reasons)),capture_verified=True,
        debit_attribution='NOT_VALIDATED',production_execution_enabled=False,entry_permission=False)
