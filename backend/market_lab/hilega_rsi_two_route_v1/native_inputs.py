"""Use the original Hilega minute loop with causal reference-open readiness."""
from datetime import datetime,time,timedelta
import json
from math import isfinite
from pathlib import Path
from ..domain import IST

ACTIVATION=Path('data/live-observation/hilega-rsi-native-v1/activation.json')

def consume(coordinator,intraday,now,*,recovered):
    from ..hilega_three_minute_v1.session import exact_rows,FiveMinuteBar,is_boundary
    now=now.astimezone(IST);rows=exact_rows(intraday,now)
    # Snapshot data are retained only in memory for the shared deterministic
    # policy. A forming candle contributes its OPEN reference, never its H/L/C.
    full=[]
    for c in intraday:
        t=c.timestamp.astimezone(IST)
        if t.date()!=now.date() or not time(9,15)<=t.time()<time(15,30) or t>now:continue
        if t+timedelta(minutes=1)<=now:
            full.append(dict(timestamp=t.isoformat(),open=float(c.open),high=float(c.high),low=float(c.low),close=float(c.close)))
        else:full.append(dict(timestamp=t.isoformat(),open=float(c.open)))
    stamps=[r['timestamp'] for r in full]
    if len(stamps)!=len(set(stamps)):raise ValueError('DUPLICATE_REFERENCE_MINUTE')
    if any(not (isfinite(r['open']) and r['open']>0) for r in full):raise ValueError('INVALID_REFERENCE_OPEN')
    coordinator.price_frames.minute_rows=sorted(full,key=lambda r:r['timestamp'])
    known={r['timestamp'] for r in full}
    start=datetime.combine(now.date(),time(14,20) if str(now.date())=='2026-11-08' else time(9,15),IST)
    grid=start+timedelta(minutes=1) if str(now.date())=='2026-11-08' else start
    bars={}
    for i in range(23 if str(now.date())=='2026-11-08' else 125):
        label=grid+timedelta(minutes=3*i);bucket=[rows.get(label+timedelta(minutes=j)) for j in range(3)]
        if all(bucket):bars[label]=FiveMinuteBar(label,float(bucket[0].open),max(float(c.high) for c in bucket),min(float(c.low) for c in bucket),float(bucket[-1].close),sum(int(getattr(c,'volume',0) or 0) for c in bucket))
    expected=coordinator._last_minute+timedelta(minutes=1) if coordinator._last_minute else start
    count=0;coordinator._missing_minute=None
    activation=None;committed=True;proven_entries=set()
    if ACTIVATION.is_file():
        control=json.loads(ACTIVATION.read_text());activation=datetime.fromisoformat(control['activated_at'])
        committed=control.get('committed',False)
        if recovered and committed:
            from ..hilega_combined_policy_v1 import VERSION
            for record in coordinator.step_audit.read_all():
                payload=record.get('payload') or {}
                if (record.get('stage')=='DIRECTIONAL_DECISION' and record.get('status')=='PROCESSED'
                        and payload.get('strategy_id')=='HILEGA_RSI_TWO_ROUTE_CONFIRMED_MIDPOINT'
                        and payload.get('strategy_version')==VERSION
                        and any(str(e).startswith('ENTRY_') for e in payload.get('accepted_events') or [])):
                    proven_entries.add(payload.get('decision_timestamp'))

    while expected in rows:
        available=expected+timedelta(minutes=1)
        if is_boundary(available) and available.time()<time(15,30) and available.isoformat() not in known:
            coordinator._missing_minute=expected
            coordinator._health(now,'WAITING_FOR_REFERENCE_OPEN',pending_boundary=available.isoformat())
            break
        coordinator.price_frames.entry_block_reason=(
            'NATIVE_CUTOVER_NOT_COMMITTED' if not committed else
            'PRE_ACTIVATION_CANDLE_NOT_TRADABLE' if activation and available<=activation else
            'RECOVERY_WITHOUT_AUDITED_ENTRY' if activation and recovered and available.isoformat() not in proven_entries else None)

        coordinator._advance(rows[expected],bars,recovered=recovered)
        count+=1;expected+=timedelta(minutes=1)
    if expected+timedelta(minutes=1)<=now and expected.time()<time(15,30):coordinator._missing_minute=expected
    return count
