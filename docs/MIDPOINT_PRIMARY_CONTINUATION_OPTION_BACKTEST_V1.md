# Midpoint Primary Continuation Option Backtest V1

This module attaches real option economics to the two continuation arms that
survived the development-stage directional classifier review.

## Frozen promoted arms

### RED bearish continuation

```text
RED reference
-> midpoint down
-> low break
-> T+3 frozen decision score = 9/9
-> TRADE_NOW
-> exact ATM PE
```

### GREEN bullish continuation

```text
GREEN reference
-> midpoint up
-> high break
-> T+3 frozen decision score >= 7/9
-> TRADE_NOW
-> exact ATM CE
```

The backtest consumes those already-frozen decisions. It does not recalculate,
retune, or optimize the score cutoffs.

## Exact option execution assumptions

At decision timestamp:

1. find the positioning row with exact `strike_offset == 0`;
2. use PE for RED bearish, CE for GREEN bullish;
3. freeze that exact instrument key;
4. enter at the next exact 1-minute candle OPEN;
5. keep the same contract for all marks;
6. never substitute another strike or contract.

Missing exact ATM, missing entry minute, or missing later path stays
unavailable. It is never synthesized.

## Measurements

Gross and 0.50 percentage-point cost-adjusted returns:

- +1m
- +3m
- +5m
- +10m
- +15m

Also:

- 15m MFE
- 15m MAE
- descriptive +5/+10/+15 target vs -5/-10 stop matrix

The target/stop matrix does not select an exit policy.

## Required review

Results must be reviewed separately by:

- RED -> PE
- GREEN -> CE
- TRAIN
- OOS-A
- OOS-B
- OOS-C
- OOS-D

No E/F/G/H are used.

The reclaim arms remain research-only and are not backtested here.
