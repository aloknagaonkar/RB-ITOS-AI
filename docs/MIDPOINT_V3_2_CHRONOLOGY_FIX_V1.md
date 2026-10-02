# Midpoint V3.2 Chronology Fix V1

The frozen-exit validation is economically informative, but one methodological
issue must be corrected before relying on drawdown and consecutive-loss metrics.

The first validation sorted trades with:

```text
(session_date, direction)
```

This is deterministic, but if two trades occur on the same date it does not
prove which one happened first.

## Fix

1. Preserve the frozen exact `entry_timestamp` from the economics result inside
   every exit-management replay row.
2. Sort validation rows by exact `entry_timestamp`.
3. Refuse to calculate chronology-dependent metrics if the timestamp is absent.

This changes **no**:
- entry signal;
- V3.2 state;
- option contract;
- stop;
- trailing rule;
- exit policy;
- P&L value.

Only ordering for:
- cumulative P&L;
- maximum drawdown;
- consecutive losses

is corrected.

After applying the patch, rerun exit-management research and then frozen-exit
validation. Mean return, win rate, payoff ratio, and PF should be unchanged.
Only chronology-dependent statistics may change.
