# EARLY_REVERSAL_CONFIRMATION_HOLDOUT_V1

## Purpose

Freeze the best structure discovered in the 54-session development cohort and validate it
without feature changes on holdout sessions.

The frozen structure is:

1. opposite-direction ALL_3 appears
2. ALL_3 survives to candle 2
3. inspect candle-2 futures OI direction
4. inspect whether futures support was maintained from candle 1
5. inspect whether futures newly flipped into alignment on candle 2
6. inspect candle-2 VWAP side
7. inspect candle-2 futures + VWAP joint support

No new feature hunting is allowed in this study.

## Practical extension

The development studies answered whether the ALL_3 run becomes persistent. This holdout
also measures whether enough underlying movement is left **after candle 2**:

- signed NIFTY spot move +5m
- +10m
- +15m
- +30m
- candle 2 -> ALL_3 run end
- MFE / MAE through the run end
- remaining ALL_3 candles

These are evaluation-only.

This is not option-premium PnL yet.

## Holdout discipline

The 54 development dates must be excluded.

The run script freezes the holdout cohort from available V1.1 audit files *before* running
the analysis. It excludes every session present in the 54-session development rows.

If the remaining audit files were previously used in other exploratory work, interpret this
as an out-of-development-cohort validation rather than a pristine never-seen holdout.
