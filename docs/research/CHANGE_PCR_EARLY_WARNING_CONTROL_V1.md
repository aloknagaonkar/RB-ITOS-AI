# CHANGE_PCR_EARLY_WARNING_CONTROL_V1

Research-only control study built on CHANGE_PCR_VALIDATION_V1.

## Why this exists

The prior lead/lag event study conditions on known transitions. It measures whether
Change-PCR mechanics were present before a flip, but cannot measure false warnings.

This control module scans every candle.

## New bounded feature

Normalized OI Dominance:

`(PE_delta - CE_delta) / (abs(PE_delta) + abs(CE_delta))`

Range:
- +1 = maximum PE-side dominance
-  0 = balanced
- -1 = maximum CE-side dominance

This avoids the unbounded-ratio instability of Change-PCR when CE delta approaches zero.

## Candidate warning

Only while the current all-3 state is directional.

A candidate warning is emitted when either:
1. 5m Change-PCR mechanics already point opposite the current all-3 state, or
2. normalized 5m dominance changes in the opposite direction from the current state.

No tuned numeric threshold is introduced in V1; only direction/sign is used.

## Lookahead

Each warning is checked for an opposite all-3 transition within:
- 5 minutes
- 10 minutes
- 15 minutes

Warnings with no transition within 15 minutes are counted as false warnings.

## Transition persistence

Every directional transition is bucketed by resulting run length:
- 1 candle
- 2 candles
- 3+ candles

This separates one-candle whipsaws from more persistent structural transitions.

## Outputs

- transitions CSV
- warnings CSV
- summary JSON

Key summary metrics:
- warning precision at 5m / 10m / 15m
- false-warning rate at 15m
- precision for persistent (3+) transitions
- results by warning type
- count of one-candle vs 2-candle vs 3+ transitions

This module does not alter any strategy or existing classification logic.
