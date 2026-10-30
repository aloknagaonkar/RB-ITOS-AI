import hashlib,hmac,json
from datetime import datetime
from zoneinfo import ZoneInfo
MODEL="HILEGA_PRODUCTION_ACCOUNT_ADAPTER_V1"
LIVE="LIVE_READ_ONLY_ACCOUNT_PINNED"
IST=ZoneInfo("Asia/Kolkata")
class AdapterBlocked(ValueError):pass
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def aware(v):
    try:t=datetime.fromisoformat(v)
    except (TypeError,ValueError):raise AdapterBlocked('TIMESTAMP_MISSING_OR_INVALID') from None
    if t.tzinfo is None:raise AdapterBlocked('AWARE_TIMESTAMP_REQUIRED')
    return t

def day(t):return t.astimezone(IST).date().isoformat()

def sign(report,pin):
    return hmac.new(bytes.fromhex(pin['key']),canonical(report),hashlib.sha256).hexdigest()

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
