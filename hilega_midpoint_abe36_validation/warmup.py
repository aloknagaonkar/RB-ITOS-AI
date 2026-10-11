from copy import deepcopy
from datetime import date
from market_lab import hilega_v2_alignment_replay_v1 as b
_days=();_c=None;_ema=None;_count=0
def update_ema(previous,price):return float(price) if previous is None else previous+2/11*(float(price)-previous)
def prepare(warmup,target):
 global _days,_c,_ema,_count
 days=tuple(d for d,_ in sorted(warmup))
 if any(d>=target for d in days):raise ValueError('FUTURE_WARMUP')
 if len(set(days))!=len(days):raise ValueError('DUPLICATE_WARMUP')
 if _c is None or days[:len(_days)]!=_days:_c=b.ExitFirstCanonical();_ema=None;_count=0;_days=()
 for d,rr in sorted(warmup)[len(_days):]:
  for bar in b.aggregate_exact_5m(b.candles(rr),date.fromisoformat(d)):_c.on_bar(bar);_ema=update_ema(_ema,bar.close);_count+=1
 _days=days
 return deepcopy(_c),_ema,_count
