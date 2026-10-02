# Midpoint V3.2 Temporal Stability and Uncertainty V1

This phase keeps the V3.2 entry and frozen exit policy unchanged.

Frozen policy:

```text
SL5_BE5_TRAIL3_AFTER10_TIME15
```

Diagnostics:
- 10,000-sample deterministic bootstrap CI for TRAIN mean and pooled OOS-A/D mean
- descriptive TRAIN-vs-OOS permutation diagnostic
- leave-one-OOS-block-out
- leave-one-month-out
- 15-trade rolling chronological windows
- composition-vs-within-segment decomposition for OI quality and outcome family

The bootstrap and permutation tests are descriptive because temporal dependence
between trades is not modeled.

No new entry filter, exit policy, stop, threshold, or parameter is selected.
OOS-E/F/G/H are not used. OOS-H remains pristine.
