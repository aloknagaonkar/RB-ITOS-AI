"""Read-only cash observation analysis; no order permission or debit attribution."""
from decimal import Decimal,InvalidOperation,ROUND_DOWN
from datetime import datetime
class Blocked(ValueError):pass

def number(v,signed=False):
    if isinstance(v,bool) or not isinstance(v,(str,int,float,Decimal)):raise Blocked('FUNDS_NUMBER_INVALID')
    try:d=Decimal(str(v))
    except InvalidOperation:raise Blocked('FUNDS_NUMBER_INVALID') from None
    if not d.is_finite() or not signed and d<0:raise Blocked('FUNDS_NUMBER_INVALID')
    return str(d)
def stamp(v):
    try:t=datetime.fromisoformat(v)
    except (ValueError,TypeError):raise Blocked('TIMESTAMP_INVALID') from None
    if t.tzinfo is None:raise Blocked('AWARE_TIMESTAMP_REQUIRED')
    return t

def funds(raw):
    if not isinstance(raw,dict) or raw.get('status')!='success':raise Blocked('FUNDS_RESPONSE_FAILED')
    try:bucket=raw['data']['available_to_trade']['cash_available_to_trade'];cash=number(bucket['total']);used=number(bucket['margin_used']['total'])
    except (KeyError,TypeError):raise Blocked('FUNDS_SCHEMA_INVALID') from None
    result=dict(cash_available_to_trade=cash,cash_margin_used=used,field='data.available_to_trade.cash_available_to_trade.total')
    for name in ('premium_present','span_exposure','mtf'):
        value=bucket['margin_used'].get(name);result[name]=number(value) if value is not None else None
    cashrows=bucket.get('cash',{})
    if not isinstance(cashrows,dict):raise Blocked('CASH_BREAKDOWN_SCHEMA_INVALID')
    result['cash_activity']={k:number(cashrows[k]) if cashrows.get(k) is not None else None
        for k in ('opening_balance','added_today','withdrawn_today','amount_from_stock_sale','unpaid_charges')}
    result['half_cash_preview']=str((max(Decimal(0),Decimal(cash))*Decimal('.50')).quantize(Decimal('.01'),rounding=ROUND_DOWN))
    return result

def delta(a,b):return str(Decimal(b)-Decimal(a)) if a is not None and b is not None else None

def compare(previous,current):
    base=dict(debit_attribution='NOT_VALIDATED',production_execution_enabled=False,entry_permission=False,
        broker_debit_added_back=False,local_reservation_deducted=False)
    if current.get('status')!='READ_ONLY_CAPTURED':return dict(base,status='EVIDENCE_UNAVAILABLE')
    if previous is None:return dict(base,status='BASELINE_ONLY')
    if previous.get('status')!='READ_ONLY_CAPTURED':return dict(base,status='PREVIOUS_EVIDENCE_UNAVAILABLE')
    if previous['account_scope']!=current['account_scope']:return dict(base,status='ACCOUNT_SCOPE_MISMATCH')
    if previous['session_date']!=current['session_date']:return dict(base,status='NEW_SESSION_BASELINE_ONLY')
    if stamp(current['started_at'])<=stamp(previous['completed_at']):return dict(base,status='OVERLAPPING_OR_NONMONOTONIC_CAPTURES')
    changes={k:delta(previous['funds_after'].get(k),current['funds_after'].get(k)) for k in ('cash_available_to_trade','cash_margin_used','premium_present')}
    porders={x['order_id']:x for x in previous['orders']};corders={x['order_id']:x for x in current['orders']}
    order_changes=[k for k,v in corders.items() if porders.get(k)!=v]
    missing_orders=sorted(set(porders)-set(corders))
    prior_fills={(x['order_id'],x['trade_id']):x for x in previous['trades']};now_fills={(x['order_id'],x['trade_id']):x for x in current['trades']}
    newfills=sorted(set(now_fills)-set(prior_fills));missingfills=sorted(set(prior_fills)-set(now_fills))
    changedfills=[k for k in set(prior_fills)&set(now_fills) if prior_fills[k]!=now_fills[k]]
    activities=[k for k in current['funds_after']['cash_activity'] if current['funds_after']['cash_activity'][k]!=previous['funds_after']['cash_activity'][k]]
    positions_changed=sorted(current['positions'],key=lambda x:(x['instrument'],x['product']))!=sorted(previous['positions'],key=lambda x:(x['instrument'],x['product']))
    drift=current['funds_before']!=current['funds_after']
    changed=(bool(order_changes or newfills or activities) or positions_changed or any(v is not None and Decimal(v)!=0 for v in changes.values()))
    status='ACTIVITY_OBSERVED_ATTRIBUTION_PENDING' if changed else 'NO_OBSERVED_CHANGE'
    if missing_orders or missingfills or changedfills:status='BROKER_EVIDENCE_REGRESSION_REVIEW_REQUIRED'
    return dict(base,status=status,cash_deltas=changes,new_order_count=len(set(corders)-set(porders)),
        changed_order_count=len(order_changes),new_fill_count=len(newfills),positions_changed=positions_changed,
        cash_activity_fields_changed=activities,funds_changed_during_capture=drift,
        missing_order_count=len(missing_orders),missing_fill_count=len(missingfills),corrected_fill_count=len(changedfills),
        capture_atomic=False,warning='Account-wide changes are observations, never per-order cash attribution')
