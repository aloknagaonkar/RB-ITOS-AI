# MIDPOINT V3.2 Temporal Dependence Robustness V1

## Purpose

The previous `MIDPOINT_V3_2_TEMPORAL_STABILITY_AND_UNCERTAINTY_V1`
showed promising OOS economics but explicitly noted that naive
trade-level bootstrap and permutation diagnostics did not model temporal
dependence.

This phase addresses that limitation without modifying any trading rule.

## Frozen system

Entry:

`MIDPOINT_STABLE_FEATURE_STATE_MACHINE_V3_2`

Exit:

`SL5_BE5_TRAIL3_AFTER10_TIME15`

Both remain unchanged.

## Research universe

Allowed:

- TRAIN
- OOS_A
- OOS_B
- OOS_C
- OOS_D

Forbidden:

- OOS_E
- OOS_F
- OOS_G
- OOS_H

The module fails if any forbidden block appears among frozen-policy rows.

## Methods

### Calendar-month cluster bootstrap

Whole calendar months are sampled with replacement. This retains all trades
inside a sampled month and therefore avoids treating within-month trades as
independent observations.

Because the number of calendar clusters is small, results remain descriptive.

### OOS-block cluster bootstrap

Whole OOS blocks A-D are sampled with replacement.

This directly tests dependence on the four development OOS blocks, while
preserving each block internally.

### Moving-block bootstrap

Circular moving blocks of 3, 5, and 10 chronologically adjacent trades are
sampled until an OOS sample of the original length is reconstructed.

The three lengths are sensitivity checks. They are not selected or tuned
using profitability.

### Worst-regime stress

The empirically worst observed OOS calendar month's frequency is multiplied
by 2x and 3x.

This asks whether expectancy remains positive if an adverse observed regime
occurs more frequently.

The worst month must **not** become a calendar trading filter.

### Chronological stability

Rolling windows of 10, 15, and 20 OOS trades report the percentage of
positive-mean windows plus min/median/max mean and profit factor.

## Governance

The output remains `NOT_PROMOTED`.

The module:

- does not modify V3.2;
- does not modify the frozen exit;
- does not search alternative exits;
- does not select thresholds;
- does not create weekday/month/OI filters;
- does not use OOS-E/F/G/H;
- does not authorize paper/live orders.

## Decision after this phase

Review the diagnostics manually.

Only if temporal-dependence evidence is sufficiently supportive should the
entire configuration be frozen for the one-time pristine OOS-H validation.

OOS-H must not be inspected or rerun before that decision.
