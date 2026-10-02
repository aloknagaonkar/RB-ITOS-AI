# Midpoint Confirm / Wait / Cancel State Machine V3.1

V3.1 corrects the main weakness discovered in V3: feature polarity and
discriminative power must be learned from TRAIN rather than assumed globally.

## TRAIN-only feature treatment

For every direction/checkpoint/feature:

```text
continuation median > reversal median
    => HIGHER_IS_BETTER

continuation median < reversal median
    => LOWER_IS_BETTER

medians equal or near-equal
    => NON_DISCRIMINATIVE
```

NON_DISCRIMINATIVE features do not contribute to the score denominator.

## T+1

T+1 is informational only:

```text
DEVELOPING_STRONG
WAIT
FAILURE_RISK
```

It never authorizes a trade entry.

## T+3

T+3 is the only research confirmation checkpoint:

```text
CONFIRM_CONTINUATION
WAIT_BASE
CANCEL_BREAKOUT
RECLAIM_WATCH
```

Price structure remains primary. OI remains a quality tier.

## Why this matters

V3 showed examples where a feature was hard-coded HIGHER_IS_BETTER even though
the TRAIN continuation median was lower than the TRAIN reversal median. V3.1
removes that contradiction.

It also removes zero-separation features from the vote so features such as
100-vs-100 acceptance or 2-vs-2 consecutive closes do not artificially change
the score.

## Leakage guard

- TRAIN derives polarity and thresholds
- A/B/C/D validate unchanged
- E/F/G/H excluded
- H pristine
- no P&L
- no order generation
