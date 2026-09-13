# Opening Red Candle Midpoint Evidence Research V1

## Objective

Research when a downside break of an early-session red 5-minute candle's
midpoint/low is likely to continue, remain sideways, or reclaim/reverse.

This phase **does not create a trading rule yet**. It builds a clean historical
event dataset so we can measure whether price momentum, option OI/premium/volume,
and PCR provide useful confirmation before entry.

## Frozen structure rules

1. Ignore the first 5-minute candle: 09:15-09:19 IST.
2. Find the first later completed RED 5-minute candle.
3. Freeze that one candle for the session.
4. Midpoint = `(High + Low) / 2`.
5. Midpoint downside break = 1-minute close below midpoint.
6. Low break = 1-minute close below the same reference candle's low.
7. The original midpoint remains active after a break.
8. Reclaim = later 1-minute close above the original midpoint.
9. Repeated midpoint crosses are counted as chop evidence.
10. One reference candle per session in V1.

## Why low break is not an automatic PE entry

After low break, the engine stores evidence snapshots at:

- T0
- T+1 minute
- T+3 minutes
- T+5 minutes

Each snapshot includes backward/current-only information.

### Price evidence

- 1m, 5m, 15m spot momentum
- EMA(5), EMA(15)
- EMA spread and 3m slope
- 15m realized volatility
- distance from original midpoint
- distance from reference low
- midpoint cross count

### Option evidence at current moving ATM

- CE/PE premium
- CE/PE OI
- CE/PE volume
- 5m premium change %
- 5m OI change %
- 5m volume change %
- CE/PE positioning states
- combined positioning state
- 15m positioning fields when available

### PCR context

- Fixed / Moving / Full PCR
- 1m/5m/15m PCR changes when available

PCR is context only in this phase.

## Future outcome labels

Future data is used only to label what happened after the low break.

- `BREAK_AND_GO`
- `BREAK_AND_BASE_THEN_GO`
- `SIDEWAYS_NO_CONTINUATION`
- `FALSE_BREAK_RECLAIM`
- `NO_LOW_BREAK`
- `NO_MIDPOINT_BREAK`

The research continuation level is deliberately fixed before analysis:

`reference_low - max(10 NIFTY points, 50% of reference candle range)`

If this level is reached within 5 minutes before midpoint reclaim:
`BREAK_AND_GO`.

If reached in 6-30 minutes before reclaim:
`BREAK_AND_BASE_THEN_GO`.

If midpoint is reclaimed first:
`FALSE_BREAK_RECLAIM`.

If neither continuation nor reclaim occurs within 30 minutes:
`SIDEWAYS_NO_CONTINUATION`.

This continuation threshold is a **research label only**, not an entry rule.

## Development universe

Only:

- TRAIN
- OOS-A
- OOS-B
- OOS-C
- OOS-D

OOS-E/F/G/H are not used. OOS-H remains untouched.

## What we will decide after this run

We will compare the evidence available at T0/T+1/T+3/T+5 across outcome groups.

Examples of questions:

- Does `PE LONG_BUILDUP` occur more often before real continuation?
- Does `CE SHORT_BUILDUP` add confirmation?
- Does PE volume expansion separate continuation from reclaim?
- Do repeated midpoint crosses identify chop?
- Does strongly negative 5m momentum improve continuation probability?
- Does PCR add incremental information after price/OI/volume?
- Is waiting 1-5 minutes after low break materially better than immediate entry?

Only after the evidence is measured will a later phase define:
`TRADE`, `WAIT`, or `CANCEL`.
