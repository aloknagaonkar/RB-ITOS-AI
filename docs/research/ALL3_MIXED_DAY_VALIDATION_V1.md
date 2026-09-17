# ALL3_MIXED_DAY_VALIDATION_V1

Purpose: finish the third leg of the frozen ALL_3 persistence hypothesis.

Hypothesis:
- Bullish days: longer BULLISH_ALL_3 persistence, shorter bearish counter-runs.
- Bearish days: longer BEARISH_ALL_3 persistence, shorter bullish counter-runs.
- Mixed/reversal days: more balanced bullish/bearish persistence.

## Frozen mixed cohort

The mixed cohort is frozen before running persistence analysis. It uses the first 18
chronological sessions labelled `MIXED_DAY` in the existing day-classification population:

- 2026-05-04
- 2026-05-05
- 2026-05-06
- 2026-05-07
- 2026-05-08
- 2026-05-11
- 2026-05-13
- 2026-05-14
- 2026-05-15
- 2026-05-21
- 2026-05-22
- 2026-05-26
- 2026-05-27
- 2026-06-03
- 2026-06-04
- 2026-06-05
- 2026-06-08
- 2026-06-09

This provides an equal 18/18/18 comparison:
- 18 bullish days
- 18 bearish days
- 18 mixed/reversal-labelled days

Total: 54 sessions.

## No changes to signal logic

The test reuses:
- moving ATM ±5
- same-strike 5m/10m/15m OI deltas
- existing horizon-state definition
- BULLISH_ALL_3 / BEARISH_ALL_3 / MIXED / INCOMPLETE
- existing run construction

No thresholds are fitted.

## What to inspect

For mixed/reversal days:
- bullish mean run length
- bearish mean run length
- absolute bull/bear mean-run difference
- bullish vs bearish total directional candles
- bullish vs bearish 3+ run counts
- whether max runs on both sides are closer than on directional days

The mixed label remains evaluation-only.
