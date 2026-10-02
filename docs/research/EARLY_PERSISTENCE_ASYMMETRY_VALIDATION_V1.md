# EARLY_PERSISTENCE_ASYMMETRY_VALIDATION_V1

## Purpose

Test whether a new opposite-direction ALL_3 run can be recognized early, at candle 1 or
candle 2, using only information available at that moment.

This follows the 54-session persistence study and `REVERSAL_CONFLUENCE_VALIDATION_V1`.

## Snapshot 1

At the first candle of a new opposite-direction ALL_3 run, record:

- current run length = 1
- completed historical target-direction run lengths
- completed historical counter-direction run lengths
- target-directional share up to the snapshot
- futures OI direction
- VWAP side
- fixed-session OI/PCR context

Outcome (evaluation only): whether the run eventually reaches 3+ candles.

## Snapshot 2

If the new run survives to a second consecutive ALL_3 candle, repeat the exact same
causal measurements with current run length = 2.

## Persistence asymmetry

`target_effective_mean - counter_completed_mean`

The target effective mean includes the currently developing causal run (1 or 2 candles).
No future run candles are used.

## No tuning

- No persistence cutoff is fitted.
- No score threshold is created.
- The natural `target directional share > 0.5` split is descriptive only.
- P1/P2 are excluded because the prior 54-session confluence run did not have usable
  P1/P2 coverage.
- Change-PCR remains diagnostic only.

The goal is to discover whether futures alignment and developing persistence asymmetry
separate genuine 3+ runs from short counter-runs early enough to be useful.
