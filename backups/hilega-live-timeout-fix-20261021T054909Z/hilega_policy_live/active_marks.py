"""Display-only bridge to the existing stream. No observer evaluation or orders."""
import json
import math
import os
from datetime import datetime, timezone

def number(value):
    if isinstance(value,bool):return None
    try:value=float(value)
    except (TypeError,ValueError):return None
    return value if math.isfinite(value) and value>0 else None

def requested_keys(data, current=None):
    current=current or datetime.now(timezone.utc)
    try:
        at=datetime.fromisoformat(data['requested_at'])
        if at.tzinfo is None or not 0<=(current-at).total_seconds()<=30:return set()
        keys=data['instrument_keys']
        if not isinstance(keys,list) or len(keys)>20:return set()
        return {k for k in keys if isinstance(k,str) and k.startswith('NSE_FO|') and len(k)<80}
    except (KeyError,TypeError,ValueError):return set()

def display_keys(publisher):
    try:data=json.loads((publisher.state_path.parent/'active-mark-requests.json').read_text())
    except (OSError,ValueError):return set()
    return requested_keys(data)

def snapshot(publisher,current=None):
    current=current or datetime.now(timezone.utc)
    catalog={str(c.get('instrument_key')):c for c in publisher.catalog}
    quotes={}
    for key in display_keys(publisher):
        tick=publisher.cache.get(key)
        if not tick:continue
        feed=tick.get('feed') or {}
        body=feed.get('firstLevelWithGreeks') or feed.get('fullFeed',{}).get('marketFF') or {}
        book=(body.get('marketLevel') or {}).get('bidAskQuote') or []
        depth=body.get('firstDepth') or (book[0] if book else {})
        ltpc=body.get('ltpc') or {}
        meta=catalog.get(key) or {}
        lot=meta.get('lot_size')
        quotes[key]=dict(instrument_key=key,ltp=number(ltpc.get('ltp')),bid=number(depth.get('bidP')),
            ask=number(depth.get('askP')),bid_quantity=number(depth.get('bidQ')),
            feed_timestamp=tick.get('at'),last_trade_timestamp=ltpc.get('ltt'),
            lot_size=lot if type(lot) is int and lot>0 else None,
            expiry=meta.get('expiry'),timestamp_basis='UPSTOX_FEED_MESSAGE_TIME')
    return dict(generated_at=current.isoformat(),stream_connected=publisher.connected,quotes=quotes,
                observation_only=True,orders_enabled=False)

def publish(publisher):
    """Errors must never interrupt existing ranking/observation processing."""
    try:
        path=publisher.state_path.parent/'active-live-quotes.json'
        temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps(snapshot(publisher),allow_nan=False))
        os.replace(temp,path)
    except Exception:pass
