# REVERSAL_CONFLUENCE_VALIDATION_V1

## Research question

When ALL_3 flips direction, is the move followed by only a short counter-run or does the
new direction persist?

This module does **not** create a reversal rule. It measures independent evidence already
available at the causal flip candle.

## Event

A reversal candidate is the first opposite-direction `BULLISH_ALL_3` /
`BEARISH_ALL_3` candle after the most recent directional ALL_3 observation.

`MIXED` / `INCOMPLETE` candles between the two states are retained as `gap_candles`.

## Outcome

The outcome is the exact contiguous length of the new ALL_3 run.

For descriptive comparison only:
- `ONE_CANDLE`
- `TWO_CANDLE`
- `THREE_PLUS`

No bucket is a trading threshold.

## Independent confluence recorded at the flip

1. Fixed-session option context:
   - session OI imbalance sign
   - session PCR change sign
   - counted supportive only when both point toward the target direction.
2. Futures OI direction.
3. VWAP side (`ABOVE` for bullish, `BELOW` for bearish).
4. Existing P1 direction, when available.
5. Existing P2-confirmed direction, when available.

The newly flipped ALL_3 state itself is **not** counted as confluence.

Change-PCR is deliberately excluded from the score because the expansion study showed
high false-warning rates.

## Interpretation

Compare the raw confluence distributions across eventual ONE_CANDLE, TWO_CANDLE and
THREE_PLUS runs. We are looking for stable separation, not fitting a cutoff.

No strategy logic, state definition, stop, ATM selection or threshold is changed.
