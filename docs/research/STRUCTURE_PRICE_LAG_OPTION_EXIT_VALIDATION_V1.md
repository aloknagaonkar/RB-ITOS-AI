# STRUCTURE_PRICE_LAG_OPTION_EXIT_VALIDATION_V1

## Purpose

This study changes **only exit management**. Entry logic is frozen from
`STRUCTURE_PRICE_LAG_EXACT_OPTION_REPLAY_V1`.

The exact-option replay showed that many trades have meaningful MFE but poor fixed-horizon
realized returns. This study asks whether dynamic exits can retain more of the available
premium move.

## Frozen entry

- new opposite ALL_3
- survives through candle 2
- candle-2 futures OI supports direction
- exact moving ATM at confirmation
- bullish -> CE, bearish -> PE
- exact next-minute option open
- no nearest strike
- no nearest time

`SPOT_LAG` remains an analysis group, not a mandatory entry rule.

## Policies

The primary existing risk policy is:

`SL5_BE5_TRAIL3_AFTER10_TIME15`

- initial stop: -5%
- breakeven arm: +5%
- trail activation: +10%
- trailing distance: 3%
- time exit: 15 minutes
- BE/trail changes become active from the next minute bar

Controls:

- `TIME_15`
- `SL5_TIME15`
- `SL5_BE5_TRAIL3_AFTER10_TIME30`

These are predeclared policy comparisons. V1 does not optimize thresholds.

## Intrabar semantics

Using 1-minute option OHLC:

1. gap through active stop -> exit at minute open
2. otherwise low touching active stop -> exit at stop price
3. high can arm BE/trailing for the next bar only
4. exact time exit uses the exact target-minute close
5. no nearest-time fallback

This avoids using the same bar's future high to protect against an earlier low.

## Reporting

For each policy:

- positive rate
- mean / median net return
- profit factor
- average winner / loser
- best / worst trade
- exit reason counts
- BE/trail activation counts
- SPOT_LAG vs SPOT_ALREADY_MOVED
- bullish CE vs bearish PE

This is still research/paper only and does not alter live execution.
