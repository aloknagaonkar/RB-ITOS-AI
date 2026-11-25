"""Prior-session indicator data for the first exact 5m candle, not setup state."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time
from math import isfinite
from .domain import IST

@dataclass(frozen=True)
class OpeningReference:
    session_date: date
    bar_timestamp: datetime
    snapshot: object

def capture_opening_reference(canonical, session_date):
    engine = canonical.bullish
    snapshot = engine.previous_indicators
    bar = engine.previous_bar
    if snapshot is None or not snapshot.ready or bar is None:
        return None
    stamp = bar.ts
    if stamp.tzinfo is None or stamp.astimezone(IST).date() >= session_date:
        return None
    values = (snapshot.rsi9, snapshot.ema3_rsi, snapshot.wma21_rsi)
    if any(value is None or not isfinite(float(value)) for value in values):
        return None
    return OpeningReference(session_date, stamp.astimezone(IST), deepcopy(snapshot))

def confirmation_reference(current, opening, minute):
    if current is not None:
        return current
    stamp = minute.astimezone(IST)
    if (opening is not None and stamp.date() == opening.session_date
            and time(9, 15) <= stamp.time() < time(9, 20)):
        return opening.snapshot
    return None
