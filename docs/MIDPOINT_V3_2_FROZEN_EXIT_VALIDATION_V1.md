# Midpoint V3.2 Frozen Exit Validation V1

This phase validates exactly one exit policy:

```text
SL5_BE5_TRAIL3_AFTER10_TIME15
```

No alternative policy search is allowed.

## Why

The policy was nominated using TRAIN only, and all OOS-A/B/C/D blocks were
positive by mean. However, TRAIN itself remained negative. Therefore the policy
is promising but cannot be promoted yet.

## Validation metrics

- win rate
- mean and median net return
- profit factor
- average winner
- average loser
- payoff ratio
- best / worst trade
- max consecutive losses
- cumulative max drawdown
- contribution of largest 1 / 3 / 5 winners
- cumulative path

Segments:
- OOS block
- BEARISH / BULLISH
- BREAK_AND_GO / BASE_THEN_GO / OTHER
- T+1 observation state
- OI quality

## Governance

The policy remains:

```text
TRAIN-NOMINATED
OOS-PROMISING
NOT PROMOTED
```

Negative TRAIN viability blocks promotion even if OOS-A/B/C/D look positive.

OOS-H remains pristine for a future final fresh test.
