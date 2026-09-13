# Midpoint Stable-Feature State Machine V3.2

V3.2 simplifies the state machine after V3.1 showed that T+1 polarity and some
small TRAIN median reversals were not stable enough to be operational.

## T+1

T+1 is observation-only:

```text
OBSERVE_STRONG
OBSERVE_MIXED
OBSERVE_WEAK
```

It never confirms an entry and never cancels a setup.

The observations are descriptive and use:
- directional momentum
- directional progress
- giveback
- acceptance
- OI quality

## T+3

T+3 is the only decision checkpoint.

Candidate stable features:
- acceptance_pct
- momentum_5m_directional
- progress_points
- giveback_from_best_checkpoint_points
- consecutive_closes
- velocity

A feature is ACTIVE only if:
1. TRAIN direction agrees with its structural meaning, and
2. TRAIN median separation exceeds a minimum effect-size threshold.

Otherwise the feature remains DIAGNOSTIC_ONLY and does not vote.

## Structural polarity

```text
acceptance_pct                       HIGHER_IS_BETTER
momentum_5m_directional              HIGHER_IS_BETTER
progress_points                      HIGHER_IS_BETTER
giveback_from_best_checkpoint_points LOWER_IS_BETTER
consecutive_closes                   HIGHER_IS_BETTER
velocity                             HIGHER_IS_BETTER
```

This prevents noisy TRAIN inversions such as "more deterioration is better"
from becoming strategy logic.

## T+3 states

```text
CONFIRM_CONTINUATION
WAIT_BASE
CANCEL_BREAKOUT
RECLAIM_WATCH
```

Price structure is primary. OI is a quality tier. Strong price plus NONE or
UNAVAILABLE OI remains WAIT_BASE rather than CONFIRM.

## Leakage guard

- thresholds/activation from TRAIN only
- structural polarity defined a priori
- OOS-A/B/C/D validation only
- E/F/G/H excluded
- H pristine
- no P&L
- no trade orders
