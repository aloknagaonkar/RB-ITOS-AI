# MIDPOINT V3.2 OOS-H Final Validation Protocol

## Objective

Perform one final untouched holdout validation of the already-frozen Midpoint V3.2 entry and exit stack.

## Why a freeze contract exists

The previous phase returned `ROBUSTNESS_SUPPORTIVE`, but the final holdout is only meaningful if the strategy cannot change after the holdout is opened.

The freeze contract records:

- strategy/version identifiers;
- entry and contract rules;
- exit policy parameters;
- transaction-cost assumption;
- predeclared final decision gate;
- SHA-256 hashes of selected implementation files.

The final replay refuses to run when a frozen file hash changes.

## Why a dedicated exit runner exists

The development exit module evaluated multiple exit candidates. Running that module on OOS-H would expose alternative-policy performance and contaminate the final holdout.

This bundle therefore contains an H-only exit replay that implements exactly one exit:

`SL5_BE5_TRAIL3_AFTER10_TIME15`

No alternative exits are calculated or persisted.

## Frozen exit semantics

For a long CE or PE option:

1. Entry is the exact next-minute OPEN from the exact frozen ATM contract.
2. Initial stop is 5% below entry.
3. When best price reaches +5%, breakeven is scheduled for the next bar.
4. When best price reaches +10%, a 3% trailing stop is scheduled for the next bar.
5. Stop changes discovered in the current candle cannot stop the trade inside that same candle.
6. If the next bar opens below the active stop, exit at OPEN.
7. Otherwise if LOW touches the active stop, exit at the stop price.
8. If no stop fires, exit at the close of the 15th one-minute candle.
9. Subtract 0.50 percentage points round-trip cost.

## Final gate

The gate is intentionally simple and frozen before H:

- operational/freeze integrity must pass;
- fewer than 10 realized trades is insufficient for a pass/fail economic conclusion;
- mean net return must be positive;
- aggregate profit factor must exceed 1.

The gate does not optimize anything.

## After OOS-H

`PASS_CANDIDATE_FOR_PAPER_TRADING_REVIEW`:
Proceed to a separate operational paper-trading readiness review.

`HOLD_INSUFFICIENT_SAMPLE`:
Do not alter the strategy based on H. Gather a new future untouched sample.

`FAIL_ECONOMICS`:
Current frozen system fails. H cannot be reused for retuning and retesting.

`FAIL_INTEGRITY`:
Discard the run as a final validation and investigate the operational/freeze violation. Do not interpret economics until integrity is restored.

Live trading remains disabled in every outcome.
