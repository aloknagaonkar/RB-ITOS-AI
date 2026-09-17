# CHANGE_PCR_PERSISTENT_DETERIORATION_V1

Research-only persistence and propagation study.

## Purpose

The previous control study showed that a single candle of normalized OI dominance deterioration
was too noisy:
- many warnings
- high false-warning rate
- low precision for persistent transitions

This module asks whether persistence or cross-horizon propagation improves the signal.

## Base feature

Normalized OI Dominance:

`(PE_delta - CE_delta) / (abs(PE_delta) + abs(CE_delta))`

Range: [-1, +1].

A move toward bullish means the value increased.
A move toward bearish means the value decreased.

## Candidate patterns

### 1-step
Current 5m normalized dominance moved toward the direction opposite the current all-3 state.

### 2-step
Two consecutive 5m candles moved toward the opposite direction.

### 3-step
Three consecutive 5m candles moved toward the opposite direction.

### Cross-horizon propagation
At the candidate candle, deterioration toward the opposite direction is visible in:
- 5m only
- 5m + 10m
- 5m + 10m + 15m

No optimized numeric thresholds are used. Only direction/sign and persistence count.

## Outcomes

For every candidate:
- opposite all-3 transition within 5m
- within 10m
- within 15m
- false warning within 15m
- resulting run length
- persistent transition = run length >= 3 candles

## Key question

Does persistence or propagation materially improve:
- transition precision
- persistent-transition precision
- false-warning rate

compared with single-candle deterioration?

No strategy logic is modified.
