# Midpoint Trade Decision Research V1

This phase has **two arms**.

## A. Bearish continuation decision

At exactly T+3 minutes after the reference-low break:

- `TRADE_NOW` = TRAIN-frozen evidence score is strong enough and midpoint has not
  already been reclaimed.
- `WAIT` = bearish structure is still alive but evidence is not strong enough.
- `CANCEL` = midpoint was already reclaimed by T+3.

Thresholds and the score cutoff are derived only from TRAIN. OOS-A/B/C/D are
validation only. No P&L is used to select the rule.

Predeclared evidence features:

- 5m spot momentum
- distance from reference low
- % closes below reference low
- consecutive closes below reference low
- new closing-low count
- net downside progress
- downside velocity
- PE 5m premium change
- CE 5m OI change

## B. Bullish reclaim research

Bullish is not ignored.

V1 studies the bullish reversal that naturally follows the same original red
reference candle:

`midpoint break down -> low break -> failure -> midpoint reclaim -> bullish test`

The same original midpoint remains the level.

At reclaim +3 minutes we record price, CE/PE OI/premium/volume and PCR context.

Future bullish outcomes are:

- `BULLISH_BREAK_AND_GO`
- `BULLISH_BASE_THEN_GO`
- `FAILED_BULLISH_RECLAIM`
- `BULLISH_SIDEWAYS`

A bullish continuation requires price to reach:

`reference_high + max(10 NIFTY points, 50% of reference-candle range)`

before a later close falls back below the original midpoint.

This is research only. It does not yet emit CE trades.

## Why not add the symmetric green-candle strategy now?

A first-green-candle / upside-midpoint-break strategy is a valid separate
hypothesis, but mixing it into this phase would create a second setup family.

First validate:
1. bearish continuation after red-candle low break;
2. bullish reversal after failed bearish break/reclaim.

If the reclaim reversal has evidence, then a later V2 can add the fully
symmetric first-green-candle bullish continuation setup.
