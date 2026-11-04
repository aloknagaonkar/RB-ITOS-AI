"""Bounded documented historical pagination and field corroboration, never time/ownership clearance."""
from datetime import date
from decimal import Decimal,InvalidOperation
from finance import need


def page(value,number,size):
    need(type(value) is dict and value.get('status')=='success' and type(value.get('data')) is list,'HISTORICAL_TRADE_RESPONSE_REQUIRED')
    metadata=[value[k] for k in ['meta_data','metadata'] if k in value]
    need(bool(metadata) and all(m==metadata[0] for m in metadata),'HISTORICAL_PAGINATION_METADATA_REQUIRED')
    info=metadata[0].get('page') if type(metadata[0]) is dict else None
    need(type(info) is dict,'HISTORICAL_PAGE_REQUIRED')
    need(info.get('page_number')==number and type(info.get('page_size')) is int and 1<=info['page_size']<=size,'HISTORICAL_PAGE_IDENTITY_CHANGED')
    count,pages=info.get('total_records'),info.get('total_pages')
    need(type(count) is int and count>=0 and type(pages) is int and 0<=pages<=5,'HISTORICAL_TOTALS_REQUIRED')
    need(len(value['data'])<=info['page_size'] and (count==0 and pages in (0,1) or count>0 and 1<=pages<=5),'HISTORICAL_PAGE_BOUNDS_INVALID')
    need(count<=pages*info['page_size'] if pages else count==0,'HISTORICAL_TOTAL_CAPACITY_INVALID')
    return value['data'],count,pages,info['page_size']


def equal(a,b):
    if isinstance(a,bool) or isinstance(b,bool):return False
    try:x,y=Decimal(str(a)),Decimal(str(b))
    except (InvalidOperation,ValueError):return False
    return x.is_finite() and y.is_finite() and x>0 and x==y


def corroborate(rows,prior,session):
    need(date.fromisoformat(session).isoformat()==session,'EXACT_HISTORY_SESSION_REQUIRED')
    need(type(rows) is list and type(prior) is list,'HISTORICAL_ROW_LIST_REQUIRED')
    invalid=sum(not isinstance(r,dict) or r.get('segment')!='FO' or r.get('trade_date')!=session for r in rows)
    matched=ambiguous=conflicting=missing=0
    for old in prior:
        need(isinstance(old,dict) and isinstance(old.get('trade_id'),str) and bool(old['trade_id']),'PRIOR_TRADE_ID_REQUIRED')
        hits=[r for r in rows if isinstance(r,dict) and r.get('trade_date')==session and r.get('segment')=='FO'
              and r.get('trade_id')==old['trade_id'] and r.get('exchange')==old.get('exchange')]
        if not hits:missing+=1;continue
        if len(hits)!=1:ambiguous+=1;continue
        row=hits[0]
        if row.get('transaction_type')==old.get('transaction_type') and type(row.get('quantity')) is int and type(old.get('quantity')) is int and row['quantity']==old['quantity'] and row['quantity']>0 and equal(row.get('price'),old.get('average_price')):matched+=1
        else:conflicting+=1
    return dict(historical_trade_rows=len(rows),prior_day_trade_rows=len(prior),matching_trade_id_exchange_side_quantity_price_rows=matched,
        ambiguous_matches=ambiguous,conflicting_matches=conflicting,unmatched_prior_rows=missing,out_of_scope_or_invalid_rows=invalid,
        execution_timestamp_contract_verified=False,full_contract_identity_verified=False,strategy_ownership_verified=False,execution_permission=False)
