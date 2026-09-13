# Midpoint V3.2 Exact Option Economics V1

This module freezes `MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2` and measures
exact-option economics without changing the state machine.

## Candidate

Only:

```text
t3_state == CONFIRM_CONTINUATION
```

is evaluated.

## Contract

```text
BEARISH -> exact moving ATM PE at T+3
BULLISH -> exact moving ATM CE at T+3
```

There is no nearest-strike fallback.

The exact instrument key is taken from the positioning row at the T+3 minute.
The same frozen instrument is then followed in the exact-instrument option OHLC
sidecar.

## Entry

Entry is the exact next-minute option OPEN after T+3.

If that minute is unavailable, the entry is unavailable; the code does not skip
ahead to a later candle.

## Economics

Gross and fixed-cost-adjusted returns:

```text
+1m +3m +5m +10m +15m
```

15-minute path diagnostics:

```text
MFE
MAE
```

First-touch diagnostics:

```text
+5 / -5
+5 / -10
+10 / -5
+10 / -10
```

Same-bar target/stop touches are explicitly `AMBIGUOUS_SAME_BAR`.

## Segments

Results are segmented by:
- BEARISH / BULLISH
- TRAIN / OOS_A / OOS_B / OOS_C / OOS_D
- OI quality
- T+1 observation state
- BREAK_AND_GO / BASE_THEN_GO

These are descriptive diagnostics only. They do not change the frozen V3.2
selection rule.

## Leakage guard

- no E/F/G/H
- H remains pristine
- no P&L threshold selection
- no state-machine modification
- no target/stop promotion
- no order generation
