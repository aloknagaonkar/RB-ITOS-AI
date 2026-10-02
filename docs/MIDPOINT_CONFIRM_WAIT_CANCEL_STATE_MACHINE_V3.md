# Midpoint Confirm / Wait / Cancel State Machine V3

## Objective

Convert the corrected V2.2 diagnostics into the first explicit research state
machine for post-boundary-break confirmation.

This remains research-only. It does not place trades.

## State flow

```text
BOUNDARY_BROKEN
      |
      v
EARLY_CHECK_T1
  |       |        |
  |       |        +--> FAILURE_RISK
  |       +-----------> WAIT
  +-------------------> EARLY_STRONG
      |
      v
FINAL_CHECK_T3
  |          |          |              |
  |          |          |              +--> RECLAIM_WATCH
  |          |          +-----------------> CANCEL_BREAKOUT
  |          +----------------------------> WAIT_BASE
  +---------------------------------------> CONFIRM_CONTINUATION
```

## Price-first hierarchy

Primary:
- acceptance
- directional momentum
- progress
- progress change
- giveback
- consecutive closes
- velocity

Secondary confirmation:
- OI support quality: STRONG / SECONDARY / NONE / UNAVAILABLE

Price can cancel a breakout even when OI remains supportive.

## RED vs GREEN

The logic intentionally does not force the same early-confirm behavior.

Bearish:
- T+1 mainly early warning
- T+3 primary confirmation

Bullish:
- T+1 can produce EARLY_STRONG when price evidence is very strong
- T+3 remains the primary final checkpoint

## Threshold derivation

Candidate numeric thresholds come from TRAIN only using the midpoint between the
TRAIN continuation median and TRAIN reversal median for each feature.

OOS-A/B/C/D validate those unchanged.

This is still candidate research logic, not a frozen production strategy.

## Leakage protection

- TRAIN threshold derivation only
- A/B/C/D validation only
- E/F/G/H excluded
- H pristine
- no option P&L used
- no trade orders
