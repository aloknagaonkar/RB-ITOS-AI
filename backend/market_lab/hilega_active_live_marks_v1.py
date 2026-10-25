"""Display-only live marks. Never mutate trade evidence or call a broker."""
import json
import math
import os
import tempfile
from datetime import datetime,timezone
from pathlib import Path
from .domain import IST

ROOT=Path('data/live-observation/hilega-strike-observation-v1')
MAX_AGE=10

def num(value):
    if isinstance(value,bool):return None
    try:value=float(value)
    except (TypeError,ValueError):return None
    return value if math.isfinite(value) else None

def project(dashboard,snapshot,current=None):
    current=current or datetime.now(timezone.utc)
    today=current.astimezone(IST).date().isoformat();out=[]
    generated=snapshot.get('generated_at');snapshot_age=None
    try:snapshot_age=(current-datetime.fromisoformat(generated)).total_seconds()
    except (TypeError,ValueError):pass
    connected=snapshot.get('stream_connected') is True and snapshot_age is not None and 0<=snapshot_age<=MAX_AGE
    for trade in dashboard.get('trades',[]):
        identity=str(trade.get('signal_boundary') or trade.get('signal_bar') or '')
        if trade.get('status')!='ACTIVE' or identity[:10]!=today:continue
        for leg in trade.get('legs') or []:
            key=leg.get('instrument_key');q=(snapshot.get('quotes') or {}).get(key) or {}
            age=None
            try:age=(current-datetime.fromisoformat(q['feed_timestamp'])).total_seconds()
            except (KeyError,TypeError,ValueError):pass
            fresh=connected and age is not None and 0<=age<=MAX_AGE
            if q.get('expiry') and str(q['expiry'])[:10]!=str(trade.get('expiry') or '')[:10]:fresh=False
            entry=num(leg.get('entry_open'));ltp=num(q.get('ltp'));bid=num(q.get('bid'));ask=num(q.get('ask'));depth=num(q.get('bid_quantity'))
            ltp_valid=fresh and entry is not None and entry>0 and ltp is not None and ltp>0
            bid_valid=fresh and entry is not None and entry>0 and bid is not None and bid>0 and ask is not None and bid<=ask and depth is not None and depth>0
            lot=q.get('lot_size')
            expiry=str(trade.get('expiry') or '')[:10]
            metadata_matches=bool(expiry and str(q.get('expiry') or '')[:10]==expiry)
            lot=lot if type(lot) is int and lot>0 and metadata_matches else None
            indicative=ltp-entry if ltp_valid else None;exit_points=bid-entry if bid_valid else None
            out.append(dict(direction=trade.get('direction'),signal_boundary=identity,instrument_key=key,
                quote_timestamp=q.get('feed_timestamp'),quote_age_seconds=round(age,3) if age is not None else None,
                status='LIVE' if ltp_valid or bid_valid else 'STALE_OR_UNAVAILABLE',
                ltp=ltp,bid=bid,ask=ask,bid_quantity=depth,lot_size=lot,
                indicative_points=indicative,estimated_exit_points=exit_points,
                indicative_one_lot_pnl=indicative*lot if indicative is not None and lot else None,
                estimated_exit_one_lot_pnl=exit_points*lot if exit_points is not None and lot and depth>=lot else None,
                timestamp_basis=q.get('timestamp_basis'),ltp_is_last_trade=True,fees_included=False))
    return dict(model='HILEGA_ACTIVE_LIVE_MARKS_V1',generated_at=current.isoformat(),stream_connected=connected,
                quotes=out,max_age_seconds=MAX_AGE,observation_only=True,execution_enabled=False)

def load(dashboard):
    now=datetime.now(timezone.utc);today=now.astimezone(IST).date().isoformat()
    keys=sorted({l['instrument_key'] for t in dashboard.get('trades',[]) if t.get('status')=='ACTIVE'
        and str(t.get('signal_boundary') or t.get('signal_bar') or '')[:10]==today
        for l in t.get('legs',[]) if str(l.get('instrument_key','')).startswith('NSE_FO|')})
    ROOT.mkdir(parents=True,exist_ok=True)
    # Atomic observation subscription request; no trade/control journal writes.
    with tempfile.NamedTemporaryFile('w',dir=ROOT,delete=False) as f:
        json.dump(dict(requested_at=now.isoformat(),instrument_keys=keys[:20]),f);temp=f.name
    os.replace(temp,ROOT/'active-mark-requests.json')
    try:snapshot=json.loads((ROOT/'active-live-quotes.json').read_text())
    except (OSError,ValueError):snapshot={}
    return project(dashboard,snapshot,now)
