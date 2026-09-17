# CHANGE_PCR_PROPAGATION_EXPANSION_V1

Frozen cross-date validation of the propagation hypothesis.

## Hypothesis

Without changing any definitions:

> 5m -> 10m -> 15m normalized OI-dominance deterioration propagation should retain
> higher 15-minute transition precision and lower false-warning rate than 5m-only
> deterioration on new frozen sessions.

## Original base cohort

7 sessions already studied:
- 2026-05-12
- 2026-05-18
- 2026-08-25
- 2026-05-20
- 2026-05-25
- 2026-05-19
- 2026-05-29

## Frozen expansion cohort

Bullish:
- 2026-06-02
- 2026-06-12
- 2026-06-16
- 2026-06-17
- 2026-06-18
- 2026-06-24

Bearish:
- 2026-06-01
- 2026-06-23
- 2026-06-29
- 2026-07-07
- 2026-07-08
- 2026-07-14

Total expansion = 12 sessions.
Combined = 19 sessions.

## Frozen logic

No changes to:
- moving ATM +/-5, 11 strikes
- exact same physical strike comparison
- 5m / 10m / 15m OI deltas
- regular PCR change
- Change-PCR definition
- normalized OI dominance definition
- all-3 state definition
- propagation definition
- 5/10/15m lookahead
- persistent outcome = resulting all-3 run length >= 3

No threshold tuning.

## Report

The expansion report compares:
- BASE_7
- EXPANSION_12
- COMBINED_19

For:
- PROP_5M_ONLY
- PROP_5M_10M
- PROP_5M_10M_15M

Metrics:
- candidate count
- 15m precision
- 15m false-warning rate
- persistent 3+ precision

The key stability checks are:
- whether precision is non-decreasing as propagation broadens
- whether false-warning rate is non-increasing as propagation broadens
- whether the expansion cohort preserves the relative improvement seen in the base cohort
