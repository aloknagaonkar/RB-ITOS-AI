# CHANGE_PCR_VALIDATION_V1

Research-only validation layer for Change-PCR.

## Purpose

Measure whether the ratio of PE OI change to CE OI change adds descriptive information
beyond the frozen OI imbalance + same-strike regular PCR-change research model.

This module does **not** alter:
- OI_PRICE_REGIME_TRANSITION_AUDIT_V1_1
- BULLISH / BEARISH horizon definitions
- BULLISH_ALL_3 / BEARISH_ALL_3
- persistence-run logic
- strategy P1/P2
- futures OI logic
- VWAP logic
- session PCR logic

## Definition

For each 5m / 10m / 15m horizon:

`Change-PCR = PE_OI_change / CE_OI_change`

If CE OI change is zero, or either delta is unavailable, Change-PCR is `None`.
No infinity, epsilon, interpolation, nearest-strike, or substitution is allowed.

## Delta pattern

Each horizon also records the sign pattern, e.g.:

- CE+/PE+
- CE+/PE-
- CE-/PE+
- CE-/PE-

Zero is explicit (CE0 or PE0); it is never forced into positive or negative.

## Descriptive mechanics

Examples:

- CE+/PE+ and Change-PCR > 1 → BOTH_BUILD_PE_DOMINANT
- CE+/PE+ and Change-PCR < 1 → BOTH_BUILD_CE_DOMINANT
- CE+/PE- → CE_BUILD_PE_UNWIND
- CE-/PE+ → CE_UNWIND_PE_BUILD
- CE-/PE- → compare unwind magnitudes, but keep the raw deltas

These labels are research descriptions only, not trade rules.

## Existing state remains frozen

Existing horizon state is still:

- BULLISH: imbalance > 0 AND regular PCR change > 0
- BEARISH: imbalance < 0 AND regular PCR change < 0
- MIXED: otherwise
- NA: unavailable

Change-PCR is deliberately excluded from this classification in V1.

## Validation sequence

First run on the three already understood sessions:

- 2026-05-12
- 2026-05-18
- 2026-08-25

Then run the unchanged audit on the four frozen expansion dates:

Bullish:
- 2026-05-20
- 2026-05-25

Bearish:
- 2026-05-19
- 2026-05-29

Then rerun this module over all seven sessions.

## Questions to answer

1. Does 5m Change-PCR deterioration precede the frozen regular-PCR/imbalance state flip?
2. Does deterioration propagate 5m → 10m → 15m?
3. Are CE+/PE- and CE-/PE+ mechanically stronger transition patterns than same-sign buildup?
4. Do 10m/15m Change-PCR help reject false 5m counter-moves?
5. Are observations stable across bullish, bearish, and reversal sessions?

No thresholds are to be promoted into strategy logic from a single session.
