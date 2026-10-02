# NIFTY OI Strength → Movement Probability V1

## Objective

Answer:

> When directional OI imbalance reaches X, how often does NIFTY move
> 10 / 20 / 30 / ... points within the next 5 or 10 minutes?

This study intentionally excludes the 15-minute forward movement horizon.

## Forward horizons

- 5 minutes
- 10 minutes

## Historical OI lookbacks

Still retained as causal inputs:

- previous 5 minutes
- previous 10 minutes
- previous 15 minutes

The 15-minute value is historical context at checkpoint T, not a 15-minute
future movement label.

## OI strength floors

- 1M
- 2M
- 3M
- 5M
- 7.5M
- 10M
- 15M

Directional imbalance:

- raw imbalance = PE delta OI - CE delta OI
- bullish directional imbalance = raw imbalance
- bearish directional imbalance = -raw imbalance

A checkpoint is eligible when directional imbalance is at least the selected
floor.

## NIFTY movement thresholds

10 through 100 points in 10-point increments.

For every combination of:
- direction
- OI lookback
- forward horizon
- OI strength floor
- NIFTY movement threshold

report:
- eligible checkpoint count
- movement hit count
- movement hit rate
- median forward excursion
- P75 excursion
- P90 excursion
- maximum excursion

## Source

Reads the auditable checkpoint dataset already produced by:

`NIFTY_OI_MOVEMENT_MAGNITUDE_ATTRIBUTION_V1`

Default:
`data/historical-evidence/nifty-oi-movement-magnitude-attribution-checkpoints-v1.csv`

No stop loss.
No option P&L.
No entry-rule modification.
No 15-minute forward movement analysis.

This is descriptive research on the previously exposed canonical population,
not fresh OOS validation.
