# NIFTY OI Movement Magnitude Attribution V1

## Research question

How much recent option OI structure is present before NIFTY moves:

- 10+ points
- 20+ points
- 30+ points
- ...
- 100+ points

This study intentionally ignores stop loss, trailing stop, option P&L, and trade
management. It is market-structure attribution only.

## Inputs

Canonical enriched historical OI checkpoints.

At each exact 5-minute checkpoint T, use only information already available at T:

- CE delta OI over last 5m / 10m / 15m
- PE delta OI over last 5m / 10m / 15m
- OI imbalance = PE delta OI - CE delta OI
- PCR change over 5m / 10m / 15m
- current PCR
- spot
- moving ATM

The OI calculations remain based on moving ATM ±5 and same physical strikes.

## NIFTY movement labels

For forward horizons 5m, 10m and 15m:

- bullish excursion = largest positive spot change among exact future 5-minute
  checkpoints inside the horizon;
- bearish excursion = largest negative spot change magnitude among exact future
  5-minute checkpoints inside the horizon.

No nearest timestamp.
No interpolation.
No future OI is used as a feature.

Important limitation:
This V1 uses exact 5-minute checkpoint spot values, not 1-minute intrabar NIFTY
high/low. Therefore a move that happens and fully reverses between checkpoints is
not captured. This is deliberate for causal/data consistency. A later V2 may
use exact 1-minute NIFTY OHLC if an authoritative historical source is available.

## Direction-normalized OI imbalance

Raw imbalance:

PE delta OI - CE delta OI

For bullish attribution:

directional imbalance = raw imbalance

For bearish attribution:

directional imbalance = -raw imbalance

Positive directional imbalance therefore means OI structure agrees with the
movement direction.

## "Minimum" reporting

Do not treat one literal historical minimum as a reliable requirement.

For each movement threshold / forward horizon / OI lookback, report:

- observed minimum
- P10 ("robust minimum")
- P25
- median
- P75
- P90
- maximum
- mean
- alignment rate

The P10 value is the lower-tail robust floor among historical checkpoints that
actually achieved the specified move.

Also report a descriptive reliability check:

Among all checkpoints whose directional imbalance is at least the P10 floor,
what percentage later achieved the requested NIFTY movement inside that forward
horizon?

Because the same exposed population is used to estimate the P10 floor and its
hit rate, this is descriptive only and is not a validated trading threshold.

## Outputs

- `data/historical-evidence/nifty-oi-movement-magnitude-attribution-v1.json`
- `data/historical-evidence/nifty-oi-movement-magnitude-attribution-v1.csv`
- `data/historical-evidence/nifty-oi-movement-magnitude-attribution-checkpoints-v1.csv`

The checkpoint CSV is intentionally auditable and contains the causal OI features
plus forward movement labels.

## Governance

- no entry rule change
- no exit rule
- no stop loss
- no option P&L
- no threshold promoted to strategy logic
- exposed canonical 90 population, therefore not fresh OOS validation
