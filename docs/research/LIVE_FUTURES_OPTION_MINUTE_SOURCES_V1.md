# LIVE FUTURES + OPTION MINUTE SOURCES V1

## Added

### `LIVE_NIFTY_FUTURES_OI_PRODUCER_V1`

Consumes exact completed 5-minute NIFTY futures candles with OI.

Classifies:

- price up + OI up -> LONG_BUILDUP
- price down + OI up -> SHORT_BUILDUP
- price up + OI down -> SHORT_COVERING
- price down + OI down -> LONG_UNWINDING

Rules:

- exact instrument continuity
- exact 5-minute continuity
- no nearest-time fallback
- OHLC sanity checks
- OI non-negative
- zero price/OI delta is degraded/unclassified

### `LIVE_OPTION_MINUTE_SOURCE_V1`

Validates the exact selected option's completed 1-minute candles.

Rules:

- exact instrument key
- exact 1-minute continuity
- no nearest-time fallback
- positive OHLC
- valid high/low envelope
- out-of-order and missing-minute failure states

## Important boundary

These modules are source/normalization components only.

They do NOT:

- make strategy decisions
- place orders
- change ALL_3 logic
- alter entry rules
- alter exit thresholds

## Next step after tests

Build `FULL_SHADOW_INTEGRATION_REPLAY_V1` that chains:

normalized ALL_3 -> C2 -> futures -> classification -> ATM option -> exact next-minute open -> 1m option bars -> exit -> ledger.
