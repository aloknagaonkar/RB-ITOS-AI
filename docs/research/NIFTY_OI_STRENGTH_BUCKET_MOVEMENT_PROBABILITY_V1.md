# NIFTY OI Strength Bucket → Movement Probability V1

## Objective

Measure NIFTY movement probabilities using **non-overlapping** directional OI
imbalance ranges instead of cumulative `>= threshold` filters.

This is designed to test whether there is a true OI "sweet zone" that gets
blurred when every larger OI value is included in all lower threshold groups.

## Forward NIFTY horizons

Only:
- next 5 minutes
- next 10 minutes

No 15-minute forward movement analysis.

## Historical OI lookbacks

Retained as causal context:
- previous 5m
- previous 10m
- previous 15m

## Directional OI imbalance

Raw:
`PE delta OI - CE delta OI`

Bullish:
`directional imbalance = raw imbalance`

Bearish:
`directional imbalance = -raw imbalance`

Only **aligned positive directional imbalance** is included in this bucket
study. Opposite-sign OI is excluded from the bucket comparison.

## Non-overlapping OI buckets

- 0–1M
- 1–2M
- 2–3M
- 3–5M
- 5–7.5M
- 7.5–10M
- 10–15M
- 15M+

Lower bound inclusive, upper bound exclusive.

## NIFTY movement thresholds

- 10 points
- 20 points
- 30 points
- 40 points
- 50 points

For each:
- bullish / bearish
- OI lookback 5m / 10m / 15m
- forward horizon 5m / 10m
- OI bucket

report:
- eligible checkpoints
- hit count
- hit rate
- median forward excursion
- P75 excursion
- P90 excursion
- maximum excursion

## Source

Reads:
`data/historical-evidence/nifty-oi-movement-magnitude-attribution-checkpoints-v1.csv`

No stop loss.
No option P&L.
No entry rule changes.
Descriptive only on the previously exposed canonical population.
