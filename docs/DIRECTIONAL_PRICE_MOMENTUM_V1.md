# Directional Price-Momentum Option Buying Strategy V1

## Goal

Detect directional NIFTY breakout-momentum moves early enough to buy CE/PE without
trying to predict the exact bottom/top. The target behaviour is to capture the
middle portion of moves like a consolidation-near-high followed by a strong
bullish expansion breakout.

## Research order

1. Price-only signal generation.
2. Freeze exact moving-ATM option instrument at signal time.
3. Backtest next-minute option open using existing option OHLC sidecars.
4. Check block consistency across TRAIN + OOS-A/B/C/D.
5. Only if price-primary strategy shows edge, compare the same trades with PCR
   context attached.
6. OOS-H remains untouched until a rule is frozen and earns final validation.

## V1 price rules

Bullish signal:

- EMA(5) > EMA(15)
- EMA(5) slope over 3 minutes > 0
- backward 5-minute spot momentum > 0
- backward 15-minute spot momentum > 0
- current close/spot > prior 20-minute maximum close
- current 1-minute move is at least 1.25x the median absolute 1-minute move from
  the prior 20 minutes
- breakout extension is no more than max(5 points, 75% of the prior 20-minute
  close range)
- same-direction 10-minute cooldown

Bearish is the exact mirror.

## Time window

09:45 to 15:10 IST.

## Option selection

At the signal minute:

- bullish -> freeze exact moving-ATM CE
- bearish -> freeze exact moving-ATM PE
- source must be the `strike_offset = 0` positioning row
- no later ATM substitution

## PCR

PCR is not used to create or reject V1 signals.

Current PCR values may be attached as diagnostic context only so that, after the
price-primary strategy is evaluated, we can make a controlled comparison:

`price strategy alone` vs `same price strategy + PCR context`.

## Leakage guard

No `forward_change_*` field is used for signal construction. All V1 features use
only the signal minute or earlier data. OOS-E/F/G/H are not used in V1
development signal construction.

## Known limitation

The existing historical evidence dataset provides one `spot` value per minute,
not underlying OHLC. V1 therefore implements close-breakout logic rather than
wick/candle-body logic. If V1 is promising, an underlying OHLC sidecar can be
added for candle-body/range confirmation without changing the frozen research
sequence.
