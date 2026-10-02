# CHANGE_PCR_TRANSITION_LEAD_LAG_V1

Research-only event study built on top of:

- OI_PRICE_REGIME_TRANSITION_AUDIT_V1_1
- CHANGE_PCR_VALIDATION_V1

It does not modify either source model.

## Goal

Test whether Change-PCR mechanics appear before frozen all-3 state transitions.

## Transition definition

A transition occurs when successive directional all-3 states change:

- BULLISH_ALL_3 -> BEARISH_ALL_3
- BEARISH_ALL_3 -> BULLISH_ALL_3

MIXED or INCOMPLETE candles between directional states are allowed; the next directional state
is compared with the prior directional state.

## Event window

For each transition T, extract:

- T-15
- T-10
- T-5
- T
- T+5
- T+10
- T+15

for each 5m / 10m / 15m horizon.

## Descriptive mechanics score

This is not a strategy score or trading threshold.

For a bullish target:
- CE_UNWIND_PE_BUILD = +2
- BOTH_BUILD_PE_DOMINANT = +1
- BOTH_UNWIND_CE_DOMINANT = +1

For a bearish target:
- CE_BUILD_PE_UNWIND = +2
- BOTH_BUILD_CE_DOMINANT = +1
- BOTH_UNWIND_PE_DOMINANT = +1

Opposite mechanics receive the negative symmetric value.
NA remains NA.

## Main questions

1. How many directional all-3 transitions occur?
2. In how many events does target-supportive 5m mechanics appear before T?
3. Does 10m and then 15m show the same direction before or around T?
4. Are pre-flip clues persistent or just one-candle noise?
5. How often does an early 5m clue fail to propagate into a directional all-3 transition?

V1 deliberately avoids threshold tuning and does not alter strategy logic.
