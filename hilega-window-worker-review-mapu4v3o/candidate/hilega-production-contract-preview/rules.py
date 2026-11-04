"""Read-only contract/quote arithmetic. Never an order permission."""
from datetime import datetime,date,timezone
from decimal import Decimal,InvalidOperation,ROUND_DOWN,ROUND_UP
from zoneinfo import ZoneInfo
IST=ZoneInfo('Asia/Kolkata');UNDERLYING='NSE_INDEX|Nifty 50'
class Blocked(ValueError):pass

def number(v,positive=False):
    if isinstance(v,bool) or not isinstance(v,(str,int,float,Decimal)):raise Blocked('INVALID_NUMBER')
    try:d=Decimal(str(v))
    except InvalidOperation:raise Blocked('INVALID_NUMBER') from None
    if not d.is_finite() or d<0 or positive and d<=0:raise Blocked('INVALID_NUMBER')
    return d

def integer(v):
    d=number(v,True)
    if d!=d.to_integral_value():raise Blocked('INVALID_INTEGER')
    return int(d)

def timestamp(v):
    try:
        if isinstance(v,bool):raise ValueError()
        if isinstance(v,(int,float)) or isinstance(v,str) and v.replace('.','',1).isdigit():
            return datetime.fromtimestamp(float(v)/1000,timezone.utc)
        t=datetime.fromisoformat(v)
        if t.tzinfo is None:raise ValueError()
        return t
    except (TypeError,ValueError,OverflowError,OSError):raise Blocked('QUOTE_TIMESTAMP_INVALID') from None

def quote_map(data,keys):
    if not isinstance(data,dict):raise Blocked('QUOTES_SCHEMA_INVALID')
    result={}
    for q in data.values():
        if not isinstance(q,dict):raise Blocked('QUOTE_ROW_INVALID')
        k=q.get('instrument_token')
        if k in keys:
            if k in result:raise Blocked('DUPLICATE_QUOTE_IDENTITY')
            result[k]=q
    if set(result)!=set(keys):raise Blocked('QUOTE_IDENTITY_MISSING')
    return result

def select(contracts,spot,offsets,lots,today,expiry=None):
    if not isinstance(offsets,list) or not 1<=len(offsets)<=5 or any(type(x)is not int or x not in range(-2,3) for x in offsets) or len(offsets)!=len(set(offsets)):
        raise Blocked('OFFSETS_MUST_BE_UNIQUE_MINUS2_TO_PLUS2')
    lots=integer(lots);spot=number(spot,True)
    if not isinstance(contracts,list):raise Blocked('CONTRACTS_SCHEMA_INVALID')
    rows=[r for r in contracts if isinstance(r,dict) and r.get('underlying_key')==UNDERLYING and r.get('segment')=='NSE_FO' and r.get('exchange')=='NSE' and r.get('instrument_type') in ('CE','PE')]
    dates=sorted({date.fromisoformat(r['expiry']) for r in rows if date.fromisoformat(r['expiry'])>=today})
    chosen=date.fromisoformat(expiry) if expiry else (dates[0] if dates else None)
    if chosen not in dates:raise Blocked('REQUESTED_EXPIRY_UNAVAILABLE')
    rows=[r for r in rows if r['expiry']==chosen.isoformat()]
    strikes=sorted({number(r.get('strike_price'),True) for r in rows})
    if len(strikes)<3:raise Blocked('INSUFFICIENT_STRIKE_GRID')
    step=min(b-a for a,b in zip(strikes,strikes[1:]));atm=min(strikes,key=lambda x:(abs(x-spot),-x))
    if not strikes[0]<spot<strikes[-1]:raise Blocked('SPOT_OUTSIDE_STRIKE_COVERAGE')
    selected=[];seen=set()
    for side in ('CE','PE'):
        for off in offsets:
            strike=atm+step*off;matches=[r for r in rows if r['instrument_type']==side and number(r['strike_price'],True)==strike]
            if len(matches)!=1:raise Blocked('CONTRACT_MISSING_OR_AMBIGUOUS')
            r=matches[0];key=r.get('instrument_key')
            if not isinstance(key,str) or not key.startswith('NSE_FO|') or key in seen:raise Blocked('CONTRACT_KEY_INVALID_OR_DUPLICATE')
            seen.add(key);lot=integer(r.get('lot_size'));freeze=integer(r.get('freeze_quantity'));minimum=integer(r.get('minimum_lot'))
            quantity=lot*lots
            if quantity%minimum or quantity>freeze:raise Blocked('QUANTITY_MINIMUM_OR_FREEZE_INVALID')
            number(r.get('tick_size'),True)
            selected.append(dict(instrument_key=key,symbol=r.get('trading_symbol'),side=side,offset=off,strike=str(strike),
                expiry=chosen.isoformat(),lot_size=lot,lots=lots,quantity=quantity,freeze_quantity=freeze))
    return dict(expiry=chosen.isoformat(),atm=str(atm),inferred_strike_step=str(step),atm_tie_rule='HIGHER_STRIKE',contracts=selected)

def quality(q,quantity,at,max_age,max_spread):
    reasons=[];age=(at-timestamp(q.get('timestamp'))).total_seconds();ltp=number(q.get('last_price'),True)
    if not 0<=age<=max_age:reasons.append('QUOTE_STALE_OR_FUTURE')
    trade_age=(at-timestamp(q.get('last_trade_time'))).total_seconds()
    if not 0<=trade_age<=60:reasons.append('LAST_TRADE_STALE_OR_FUTURE')
    buy=q.get('depth',{}).get('buy',[]);sell=q.get('depth',{}).get('sell',[])
    bids=[x for x in buy if number(x.get('price'))>0 and number(x.get('quantity'))>0]
    asks=[x for x in sell if number(x.get('price'))>0 and number(x.get('quantity'))>0]
    if not bids or not asks:raise Blocked('TWO_SIDED_DEPTH_UNAVAILABLE')
    bid=max(number(x['price'],True) for x in bids);ask=min(number(x['price'],True) for x in asks)
    if bid>ask:reasons.append('CROSSED_BOOK')
    spread=(ask-bid)/((ask+bid)/2)*100
    if spread>max_spread:reasons.append('SPREAD_ABOVE_PREVIEW_LIMIT')
    askqty=sum(integer(x['quantity']) for x in asks if number(x['price'])==ask)
    bidqty=sum(integer(x['quantity']) for x in bids if number(x['price'])==bid)
    if askqty<quantity:reasons.append('BEST_ASK_DEPTH_BELOW_QUANTITY')
    if bidqty<quantity:reasons.append('BEST_BID_DEPTH_BELOW_QUANTITY')
    if number(q.get('volume'))==0:reasons.append('ZERO_VOLUME')
    return dict(ltp=str(ltp),bid=str(bid),ask=str(ask),spread_pct=str(spread),quote_age_seconds=round(age,3),
        last_trade_age_seconds=round(trade_age,3),best_bid_quantity=bidqty,best_ask_quantity=askqty,reasons=reasons)

def assess(mapping,quotes,cash,market,at,buffer,max_age=10,max_spread=Decimal('2')):
    cash=number(cash);buffer=number(buffer);cap=(cash*Decimal('.50')).quantize(Decimal('.01'),rounding=ROUND_DOWN)
    legs=[]
    for r in mapping['contracts']:
        leg=dict(r)
        try:
            q=quality(quotes[r['instrument_key']],r['quantity'],at,max_age,number(max_spread,True));leg.update(q)
            leg['estimated_cost']=(Decimal(q['ask'])*r['quantity']+buffer).quantize(Decimal('.01'),rounding=ROUND_UP)
        except (Blocked,KeyError,TypeError,AttributeError,IndexError) as exc:
            leg.update(reasons=[str(exc) if isinstance(exc,Blocked) else 'QUOTE_SCHEMA_INVALID'],estimated_cost=None)
        legs.append(leg)
    sides=[]
    for side in ('CE','PE'):
        chosen=[x for x in legs if x['side']==side];complete=all(x['estimated_cost'] is not None for x in chosen)
        total=sum((x['estimated_cost'] for x in chosen),Decimal(0)) if complete else None
        reasons=sorted({r for x in chosen for r in x['reasons']})
        if market!='NORMAL_OPEN':reasons.append('MARKET_NOT_NORMAL_OPEN')
        if total is None or total>cap or cap<=0:reasons.append('COST_UNKNOWN_OR_OVER_HALF_CASH_CAP')
        sides.append(dict(side=side,estimated_cost=str(total) if total is not None else None,half_cash_cap=str(cap),
            preview_checks_passed=not reasons,reasons=reasons,entry_permission=False))
    for leg in legs:
        if leg['estimated_cost'] is not None:leg['estimated_cost']=str(leg['estimated_cost'])
    return dict(legs=legs,baskets=sides,available_cash=str(cash),half_cash_cap=str(cap),
        buffer_per_leg=str(buffer),allocation_fraction='0.50',entry_permission=False,production_execution_enabled=False)
