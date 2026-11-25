"""Conservative review of ambiguous broker timestamp pairs. Never alters timestamps."""
from datetime import datetime,timezone
import re
from zoneinfo import ZoneInfo
IST=ZoneInfo('Asia/Kolkata')

def parse(value):
    if not isinstance(value,str) or not re.search(r'\d{2}:\d{2}:\d{2}',value):raise ValueError('BROKER_TIMESTAMP_MISSING_OR_INVALID')
    try:t=datetime.fromisoformat(value)
    except ValueError:
        try:t=datetime.strptime(value,'%d-%b-%Y %H:%M:%S')
        except ValueError:raise ValueError('BROKER_TIMESTAMP_MISSING_OR_INVALID') from None
    naive=t.tzinfo is None
    return (t.replace(tzinfo=IST) if naive else t).astimezone(timezone.utc),naive

def inspect_book(raw_orders,raw_trades,*,observed_at):
    observed,_=parse(observed_at);orders={};examples=[];parse_issues=0
    if not all(isinstance(x,dict) and x.get('status')=='success' and isinstance(x.get('data'),list) for x in (raw_orders,raw_trades)):
        return dict(status='DEFER_SCHEMA_VALIDATION_TO_ORIGINAL_NORMALIZER',review_required=False,parse_issues=0,examples=[],timestamps_modified=False)
    for row in raw_orders['data']:
        if isinstance(row,dict) and isinstance(row.get('order_id'),str):orders[row['order_id']]=row
    suspicious=0
    for row in raw_trades['data']:
        if not isinstance(row,dict):continue
        order=orders.get(row.get('order_id'))
        if not order:continue
        try:placed,pnaive=parse(order.get('order_timestamp'));filled,fnaive=parse(row.get('exchange_timestamp'))
        except ValueError:parse_issues+=1;continue
        gap=(filled-placed).total_seconds()
        exact_offset=pnaive and fnaive and abs(gap)==19800
        if exact_offset:suspicious+=1
        flags=dict(future_trade=filled>observed,trade_before_order=filled<placed,
            wrong_ist_session=filled.astimezone(IST).date()!=observed.astimezone(IST).date(),exact_naive_utc_ist_offset_pattern=exact_offset)
        if any(flags.values()) and len(examples)<10:
            examples.append(dict(**flags,order_timestamp_utc=placed.isoformat(),trade_timestamp_utc=filled.isoformat(),trade_minus_order_seconds=gap))
    return dict(status='BROKER_TIMESTAMP_SEMANTICS_UNVERIFIED' if suspicious else 'NO_EXACT_OFFSET_PATTERN_DETECTED',
        review_required=bool(suspicious),suspected_offset_rows=suspicious,order_rows=len(raw_orders['data']),trade_rows=len(raw_trades['data']),
        parse_issues=parse_issues,examples=examples,timestamps_modified=False,
        broker_timezone_contract_independently_confirmed=False,not_a_certificate_of_chronological_validity=True)
