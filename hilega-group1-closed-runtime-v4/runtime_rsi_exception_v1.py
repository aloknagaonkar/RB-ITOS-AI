"""Unchanged RSI exception arithmetic extracted from reviewed research; no file or broker access."""
import math

def exception_allows(lock_side,entry_side,rsi,ema):
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=100 for v in (rsi,ema)):
        raise ValueError('INVALID_COMPLETED_RSI_EMA')
    return ((lock_side=='BEARISH' and entry_side=='BULLISH' and rsi>40 and ema>40)
        or (lock_side=='BULLISH' and entry_side=='BEARISH' and rsi<60 and ema<60))
