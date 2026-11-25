"""Regular-session timing, causal candle aggregation and shared gate evidence."""
from datetime import datetime, time, timedelta
from math import isfinite
from .hilega_milega_strategy_v1 import FiveMinuteBar
from ..domain import IST

INTERVAL_MINUTES = 3
MIN_PASSES = 2

def is_boundary(at):
    at=at.astimezone(IST)
    start=datetime.combine(at.date(),time(9,15),tzinfo=IST)
    return (at.second==0 and at.microsecond==0 and time(9,18)<=at.time()<=time(15,30)
            and (at-start).total_seconds()%180==0)

def finite(value):
    return (value is not None and not isinstance(value,bool)
            and isinstance(value,(int,float)) and isfinite(value))

def strength_gap_evidence(gap,previous_gap,strength,consecutive,minimum=None):
    minimum=MIN_PASSES if minimum is None else minimum
    if minimum not in (2,3):raise ValueError('INVALID_STRENGTH_GAP_MIN_PASSES')
    available=all(finite(v) for v in (gap,previous_gap,strength)) and consecutive is True
    flags=dict(gap_positive_pass=finite(gap) and gap>0,
               wma_threshold_pass=finite(strength) and strength>=0.75,
               gap_expanding_pass=finite(gap) and finite(previous_gap) and consecutive is True and gap>previous_gap)
    count=sum(flags.values())
    return dict(strength_gap_evidence_available=available,strength_gap_pass_count=count,
                strength_gap_min_passes=minimum,strength_gap_pass=available and count>=minimum,**flags)

def exact_rows(intraday,now):
    now=now.astimezone(IST);rows={}
    for candle in intraday:
        stamp=candle.timestamp
        if stamp.tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
        t=stamp.astimezone(IST)
        if t.second or t.microsecond:raise ValueError('MINUTE_ALIGNMENT_REQUIRED')
        if t.date()!=now.date() or not time(9,15)<=t.time()<time(15,30) or t+timedelta(minutes=1)>now:continue
        if t in rows:raise ValueError('DUPLICATE_COMPLETED_MINUTE')
        values=[getattr(candle,k) for k in ('open','high','low','close')]
        if not all(finite(v) and v>0 for v in values):raise ValueError('INVALID_MINUTE_OHLC')
        o,h,l,c=values
        if h<max(o,l,c) or l>min(o,c):raise ValueError('INVALID_MINUTE_OHLC')
        rows[t]=candle
    return rows

def aggregate_exact_3m(candles,session_date,*,require_full_session=False):
    end=datetime.combine(session_date,time(15,30),tzinfo=IST)
    rows=exact_rows(candles,end);bars=[]
    start=datetime.combine(session_date,time(9,15),tzinfo=IST)
    for slot in range(125):
        label=start+timedelta(minutes=3*slot)
        bucket=[rows.get(label+timedelta(minutes=i)) for i in range(3)]
        if not any(bucket):
            if require_full_session:raise ValueError('MISSING_3M_CANDLE:'+label.isoformat())
            continue
        if not all(bucket):raise ValueError('INCOMPLETE_3M_CANDLE:'+label.isoformat())
        bars.append(FiveMinuteBar(label,float(bucket[0].open),max(float(c.high) for c in bucket),
                    min(float(c.low) for c in bucket),float(bucket[-1].close),sum(int(c.volume or 0) for c in bucket)))
    return bars

def consume_minutes(self,intraday,now,*,recovered):
    now=now.astimezone(IST)
    rows=exact_rows(intraday,now);bars={}
    start=datetime.combine(now.date(),time(9,15),tzinfo=IST)
    for slot in range(125):
        label=start+timedelta(minutes=3*slot)
        bucket=[rows.get(label+timedelta(minutes=i)) for i in range(3)]
        if all(bucket):
            bars[label]=FiveMinuteBar(label,float(bucket[0].open),max(float(c.high) for c in bucket),
                        min(float(c.low) for c in bucket),float(bucket[-1].close),sum(int(getattr(c,'volume',0) or 0) for c in bucket))
    expected=self._last_minute+timedelta(minutes=1) if self._last_minute else start
    processed=0;self._missing_minute=None
    while expected in rows:
        self._advance(rows[expected],bars,recovered=recovered)
        processed+=1;expected+=timedelta(minutes=1)
    if expected+timedelta(minutes=1)<=now and expected.time()<time(15,30):
        self._missing_minute=expected
        self._health(now,'WAITING_FOR_EXACT_MINUTE',missing_minute=expected.isoformat())
    return processed

def session_close_price(intraday,at):
    at=at.astimezone(IST)
    if at.time()!=time(15,30):raise ValueError('REGULAR_SESSION_CLOSE_REQUIRED')
    rows=exact_rows(intraday,at)
    last=rows.get(at-timedelta(minutes=1))
    return float(last.close) if last is not None else None
