"""Cross-endpoint comparison only. No inferred timezone, timestamp shift, ownership or clearance."""
from datetime import datetime
from decimal import Decimal,InvalidOperation
import re

def need(ok,reason):
    if not ok:raise ValueError(reason)
def parse(value):
    need(isinstance(value,str) and len(value)<=128,'TIMESTAMP_NOT_AVAILABLE')
    try:return datetime.fromisoformat(value)
    except ValueError:
        try:return datetime.strptime(value,'%d-%b-%Y %H:%M:%S')
        except ValueError:raise ValueError('TIMESTAMP_NOT_PARSEABLE') from None

def public_time(value):
    if value is None:return None
    try:return parse(value).isoformat()
    except ValueError:return None

def delta(a,b):
    try:x,y=parse(a),parse(b)
    except ValueError:return dict(seconds=None,basis='TIMESTAMP_UNAVAILABLE')
    if (x.tzinfo is None)!=(y.tzinfo is None):return dict(seconds=None,basis='MIXED_OFFSET_AND_NAIVE_NOT_INFERRED')
    return dict(seconds=(x-y).total_seconds(),basis='EXPLICIT_OFFSETS' if x.tzinfo is not None else 'NAIVE_WALL_CLOCK_ONLY')

def price_equal(a,b):
    if isinstance(a,bool) or isinstance(b,bool):return False
    try:x,y=Decimal(str(a)),Decimal(str(b))
    except InvalidOperation:return False
    return x.is_finite() and y.is_finite() and x==y

def compare_trade(day_trade,per_order,history):
    matches=[r for r in per_order if isinstance(r,dict) and r.get('order_id')==day_trade.get('order_id') and r.get('trade_id')==day_trade.get('trade_id')]
    result=dict(match_count=len(matches),unique_fill_match=False,timezone_contract_confirmed=False,timestamps_modified=False,execution_permission=False)
    if len(matches)!=1:return result
    trade=matches[0]
    keys=('order_id','trade_id','instrument_token','product','transaction_type')
    identity=all(isinstance(day_trade.get(k),str) and day_trade.get(k)==trade.get(k) for k in keys)
    quantity=type(day_trade.get('quantity')) is int and type(trade.get('quantity')) is int and day_trade['quantity']==trade['quantity'] and day_trade['quantity']>0
    same_price=price_equal(day_trade.get('average_price'),trade.get('average_price'))
    selected=[r for r in history if isinstance(r,dict) and r.get('order_id')==day_trade.get('order_id')]
    history_identity=bool(history) and len(selected)==len(history)
    events=[]
    for row in selected:
        status=row.get('status');safe=status if isinstance(status,str) and re.fullmatch(r'[a-zA-Z ]{1,80}',status) else 'UNRECOGNIZED'
        events.append(dict(status=safe,order_timestamp=public_time(row.get('order_timestamp')),exchange_timestamp=public_time(row.get('exchange_timestamp'))))
    result.update(unique_fill_match=identity and quantity and same_price,identity_fields_match=identity,quantity_matches=quantity,price_matches=same_price,
        day_trade_order_timestamp=public_time(day_trade.get('order_timestamp')),day_trade_exchange_timestamp=public_time(day_trade.get('exchange_timestamp')),
        per_order_trade_order_timestamp=public_time(trade.get('order_timestamp')),per_order_trade_exchange_timestamp=public_time(trade.get('exchange_timestamp')),
        day_minus_per_order_exchange_time=delta(day_trade.get('exchange_timestamp'),trade.get('exchange_timestamp')),
        history_identity_matches_request=history_identity,order_history_rows=len(history),order_history_events=events[:20])
    return result
