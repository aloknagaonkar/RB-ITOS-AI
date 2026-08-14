from __future__ import annotations
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import pandas as pd
IST='Asia/Kolkata'
@dataclass(frozen=True)
class HistoricalDRIEvent:
    event_id: str
    timestamp: str
    direction: str
    setup_type: str
    trigger_level: float
    invalidation_level: float
    fresh_until: str
    stage: str='EARLY'
    source: str='HISTORICAL_DRI_1M'

def detect_historical_dri_events(candles_1m: pd.DataFrame, *, swing_lookback: int=5, freshness_minutes: int=4, minimum_body_ratio: float=0.55):
    work=candles_1m.copy()
    ts=pd.to_datetime(work['timestamp'],errors='coerce',utc=True)
    work=work.loc[ts.notna()].copy(); work['timestamp']=ts.loc[ts.notna()].dt.tz_convert(IST)
    for col in ('open','high','low','close'): work[col]=pd.to_numeric(work[col],errors='coerce')
    work=work.dropna(subset=['timestamp','open','high','low','close']).sort_values('timestamp').reset_index(drop=True)
    if len(work)<31: return ()
    work['ema10']=work['close'].ewm(span=10,adjust=False).mean(); work['ema30']=work['close'].ewm(span=30,adjust=False).mean()
    events=[]; last_direction=None; last_event_ts=None
    for idx in range(max(30,swing_lookback),len(work)):
        row=work.iloc[idx]; prior=work.iloc[idx-swing_lookback:idx]
        rng=max(float(row['high']-row['low']),1e-9); body=abs(float(row['close']-row['open']))/rng
        bullish=float(row['close'])>float(prior['high'].max()) and float(row['ema10'])>float(row['ema30']) and body>=minimum_body_ratio and float(row['close'])>float(row['open'])
        bearish=float(row['close'])<float(prior['low'].min()) and float(row['ema10'])<float(row['ema30']) and body>=minimum_body_ratio and float(row['close'])<float(row['open'])
        if not bullish and not bearish: continue
        direction='BULLISH' if bullish else 'BEARISH'; moment=pd.Timestamp(row['timestamp'])
        if last_direction==direction and last_event_ts is not None and moment-last_event_ts<=timedelta(minutes=10): continue
        trigger=float(row['close']); invalidation=float(prior['low'].min()) if bullish else float(prior['high'].max())
        setup='EARLY_1M_BULLISH_BREAK' if bullish else 'EARLY_1M_BEARISH_BREAK'
        token=hashlib.sha1(f'{moment.isoformat()}|{direction}|{trigger:.4f}'.encode()).hexdigest()[:12]
        events.append(HistoricalDRIEvent(f'HDRI-{token}',moment.isoformat(),direction,setup,round(trigger,4),round(invalidation,4),(moment+timedelta(minutes=freshness_minutes)).isoformat()))
        last_direction=direction; last_event_ts=moment
    return tuple(events)
