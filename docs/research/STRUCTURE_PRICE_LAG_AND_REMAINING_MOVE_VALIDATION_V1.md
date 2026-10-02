# STRUCTURE_PRICE_LAG_AND_REMAINING_MOVE_VALIDATION_V1

## Purpose

Validate, on untouched older sessions, the hypothesis discovered in the 54-session
development cohort:

> Once a new opposite ALL_3 run survives to candle 2 and futures OI confirms the new
> direction, events where spot has not yet followed the signal may have more remaining
> directional opportunity than events where spot has already moved.

This study also quantifies how much NIFTY movement and how many same-direction ALL_3
candles remain after confirmation.

## Frozen structural gate

An event is included only when:

1. a new opposite-direction ALL_3 run appears,
2. the run survives through candle 2,
3. candle-2 futures OI direction supports the new ALL_3 direction.

No strategy rule is changed.

## Frozen price-lag definition

At candle 2:

- `SPOT_LAG`: target-signed spot move from candle 1 to candle 2 <= 0
- `SPOT_ALREADY_MOVED`: target-signed spot move from candle 1 to candle 2 > 0

No fitted point threshold is used.

## Remaining-move metrics

From the candle-2 confirmation timestamp:

- remaining observed same-direction ALL_3 candles
- remaining observed ALL_3 minutes
- directional move to observed ALL_3 run end
- directional move to session close
- directional move at +5/+10/+15/+30/+60 minutes
- MFE / MAE at those windows
- whether +20/+30/+40/+50/+75/+100 NIFTY points are reached
- candles/minutes required to hit each target
- whether the target is hit while the same ALL_3 run is still active

The point levels are reporting bins only, not entry or exit thresholds.

## Censoring

If a same-direction ALL_3 run continues into the last observed candle of the session,
`all3_run_censored_by_session_end=true`.

Such a run may have continued had the market remained open. Therefore run-end metrics are
described as **observed run end**, not complete latent run end.

Fixed-horizon and session-close outcomes are still directly observed when data exists.

## Validation cohort

The intended independent validation cohort is the older OOS-E/F/G/H blocks:

- OOS-E: 20 sessions
- OOS-F: 20 sessions
- OOS-G: 20 sessions
- OOS-H: 20 sessions

Total: 80 sessions.

These are outside the 100-session Apr-17 to Sep-08 universe previously used for
development + structural holdout.

## Important option interpretation

Do not translate a 50-point NIFTY move mechanically into a fixed option-premium move.
ATM delta may make 50 index points resemble roughly 25 premium points as a first-order
intuition, but actual option P&L depends on delta, gamma, IV, theta, strike, spread,
execution timing and expiry.

Exact option replay belongs in a later phase.
