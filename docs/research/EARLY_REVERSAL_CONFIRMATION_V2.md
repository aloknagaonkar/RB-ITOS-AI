# EARLY_REVERSAL_CONFIRMATION_V2

## Purpose

Follow-up to `EARLY_PERSISTENCE_ASYMMETRY_VALIDATION_V1`.

The prior study showed that:
- futures OI alignment was the strongest early independent discriminator,
- candle 2 was materially stronger than candle 1,
- VWAP helped but was secondary,
- historical persistence asymmetry and directional-share majority were weak,
- fixed-session OI/PCR did not discriminate reversals well.

V2 therefore focuses on **the evolution of futures OI and VWAP between candle 1 and candle 2**.

## Event

A new opposite-direction `BULLISH_ALL_3` / `BEARISH_ALL_3` run after the most recent
directional ALL_3 observation.

MIXED/INCOMPLETE gaps are retained.

## Candle 1

Record:
- futures direction support
- futures OI status
- target-direction futures streak
- VWAP support
- futures + VWAP joint support
- fixed-session OI/PCR context (background only)

## Candle 2

Only if the new ALL_3 run survives to a second candle, record:
- whether futures remains aligned
- whether futures flips into alignment
- whether target futures OI streak strengthens
- whether VWAP remains aligned
- whether VWAP crosses into alignment
- futures + VWAP joint support

## Outcome

Evaluation only:
- does the final contiguous ALL_3 run reach 3+ candles?

## Important

No entry rule or cutoff is created.
Candle-2 statistics are conditional on surviving to candle 2.
No thresholds are optimized.
