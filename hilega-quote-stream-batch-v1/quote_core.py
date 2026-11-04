import math,json
from datetime import date,datetime,timezone
from zoneinfo import ZoneInfo
INDEX='NSE_INDEX|Nifty 50';IST=ZoneInfo('Asia/Kolkata')
def need(ok,code):
    if not ok:raise ValueError(code)
def positive(v):return type(v) in (int,float) and math.isfinite(v) and v>0
def stamp(v):
    if isinstance(v,str) and not v.isdigit():
        t=datetime.fromisoformat(v.replace('Z','+00:00'));need(t.tzinfo is not None and t.utcoffset() is not None,'NAIVE_QUOTE_TIMESTAMP_REJECTED');return t
    need(type(v) in (int,float,str) and not isinstance(v,bool),'QUOTE_TIMESTAMP_REQUIRED')
    n=float(v);need(math.isfinite(n) and 1e12<=n<1e14,'EPOCH_MILLISECONDS_REQUIRED');return datetime.fromtimestamp(n/1000,timezone.utc)
def quote_map(body,keys):
    need(isinstance(body,dict) and body.get('status')=='success' and isinstance(body.get('data'),dict),'QUOTE_RESPONSE_SCHEMA_REQUIRED');out={}
    for q in body['data'].values():
        need(isinstance(q,dict),'QUOTE_ROW_SCHEMA_REQUIRED');k=q.get('instrument_token')
        need(k in keys and k not in out,'QUOTE_IDENTITY_OR_DUPLICATE_ERROR');out[k]=q
    need(set(out)==set(keys),'QUOTE_COVERAGE_INCOMPLETE');return out

def basket(contracts,spot,today):
    need(positive(spot),'POSITIVE_INDEX_PRICE_REQUIRED');lookup={}
    for c in contracts:
        if not isinstance(c,dict) or c.get('underlying_key')!=INDEX or c.get('exchange')!='NSE' or c.get('segment')!='NSE_FO' or c.get('instrument_type') not in {'CE','PE'}:continue
        if date.fromisoformat(c['expiry'])<today:continue
        need(positive(c.get('strike_price')) and type(c.get('lot_size')) is int and c['lot_size']>0,'VALID_CONTRACT_METADATA_REQUIRED')
        need(isinstance(c.get('instrument_key'),str) and c['instrument_key'].startswith('NSE_FO|'),'VALID_CONTRACT_KEY_REQUIRED')
        key=(c['expiry'],c['strike_price'],c['instrument_type']);need(key not in lookup,'AMBIGUOUS_CONTRACT');lookup[key]=c
    need(bool(lookup),'CURRENT_CONTRACTS_REQUIRED');expiry=min(k[0] for k in lookup)
    strikes=sorted({k[1] for k in lookup if k[0]==expiry and (expiry,k[1],'CE') in lookup and (expiry,k[1],'PE') in lookup})
    need(len(strikes)>=5,'FIVE_PAIRED_STRIKES_REQUIRED');i=min(range(len(strikes)),key=lambda i:(abs(strikes[i]-spot),strikes[i]));need(i>=2 and i+2<len(strikes),'ATM_TWO_NEIGHBOURS_REQUIRED')
    result={}
    for strike in strikes[i-2:i+3]:
        for side in ('CE','PE'):
            c=lookup[expiry,strike,side];key=c['instrument_key'];need(key not in result,'DUPLICATE_CONTRACT_KEY');result[key]={k:c[k] for k in ('instrument_key','expiry','strike_price','instrument_type','lot_size','underlying_key')}
    return result

def decode(message,metadata):
    if isinstance(message,str):message=json.loads(message)
    need(isinstance(message,dict),'STREAM_MESSAGE_SCHEMA_REQUIRED')
    feeds=message.get('feeds')
    if not isinstance(feeds,dict) or not feeds:return {}
    at=stamp(message.get('currentTs'));rows={}
    for key,feed in feeds.items():
        if key not in metadata or not isinstance(feed,dict):continue
        full=feed.get('fullFeed') or {};body=full.get('marketFF') or {};ltpc=body.get('ltpc') or {};levels=(body.get('marketLevel') or {}).get('bidAskQuote') or [];depth=levels[0] if levels and isinstance(levels[0],dict) else {}
        rows[key]=dict(**metadata[key],ltp=number(ltpc.get('ltp')),bid=number(depth.get('bidP')),ask=number(depth.get('askP')),bid_quantity=number(depth.get('bidQ')),ask_quantity=number(depth.get('askQ')),feed_timestamp=at.isoformat(),last_trade_timestamp=ltpc.get('ltt'),timestamp_basis='UPSTOX_FEED_MESSAGE_TIME')
    return rows

def valid(q,now):
    try:age=(now-stamp(q.get('feed_timestamp'))).total_seconds()
    except (ValueError,TypeError,OverflowError):return False
    return 0<=age<=10 and all(positive(q.get(k)) for k in ('ltp','bid','ask','bid_quantity','ask_quantity')) and q['bid']<=q['ask']


def number(value):
    if isinstance(value,bool):return None
    try:value=float(value)
    except (ValueError,TypeError):return None
    return value if math.isfinite(value) and value>0 else None
