# STRUCTURE_PRICE_LAG_EXACT_OPTION_REPLAY_V1

This stage converts the validated structural study into exact historical CE/PE economics.

## Frozen signal context

Candidate events already satisfy:

1. new opposite ALL_3,
2. survives through candle 2,
3. candle-2 futures OI supports the new direction.

The previously validated `SPOT_LAG` label is preserved as a grouping variable; it is not
made into a hard trade rule here.

## Exact contract / execution

- bullish -> CE
- bearish -> PE
- exact moving ATM at candle-2 confirmation, resolved from positioning evidence
- exact option instrument key
- entry = exact next-minute option candle OPEN
- no nearest-strike fallback
- no nearest-time fallback
- missing exact evidence = unavailable trade, not substituted data

This mirrors the repo's earlier exact-economics convention.

## What V1 measures

For every exact trade:

- option net return at +1/+3/+5/+10/+15/+30/+60m
- option MFE/MAE over 15/30/60m
- SPOT_LAG versus SPOT_ALREADY_MOVED
- bullish CE and bearish PE separately
- option premium points and percentage at the exact timestamp where NIFTY first reaches
  +20/+30/+40/+50/+75/+100 directional points

This directly tests the practical intuition "if NIFTY moves 50 points, how many option
points did the selected ATM contract actually capture?" No 0.5-delta assumption is used.

## Costs

Fixed round-trip cost: 0.5 percentage points, matching prior exact-option research.
This is descriptive economics, not a finalized execution/risk policy.

## Important

Point targets are reporting bins, not exit rules. The study does not optimize thresholds.
