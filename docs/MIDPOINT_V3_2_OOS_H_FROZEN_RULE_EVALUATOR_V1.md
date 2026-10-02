# OOS-H Frozen Rule Evaluation Design

## Problem

The original V3.2 development pipeline is guarded against OOS-H and should stay
that way. In addition, its retrospective `build_events()` function uses known
future outcome labels to restrict diagnostic events.

That behavior must not be carried into a final holdout evaluator.

## Holdout-safe rule

Candidate selection must depend only on information available through T+3:

- reference structure;
- boundary break;
- T+1 observations;
- T+3 price features;
- T+1 -> T+3 OI transition;
- frozen TRAIN-derived `t3_train_only_rules`.

Future continuation/reversal labels are never used by the H evaluator.

## Frozen economics

For each H event with `t3_state == CONFIRM_CONTINUATION`, the evaluator calls
the existing exact-option `build_trade()` implementation. This preserves:

- exact moving ATM at T+3;
- requested CE/PE side;
- no nearest-strike fallback;
- exact next-minute OPEN;
- exact 15-minute contract replay.

The subsequent H-only frozen exit module applies only:

`SL5_BE5_TRAIL3_AFTER10_TIME15`

## Governance

Running the H evaluator consumes OOS-H as the final pristine holdout.
Irrespective of PASS/HOLD/FAIL, H must never become a fresh holdout again.
