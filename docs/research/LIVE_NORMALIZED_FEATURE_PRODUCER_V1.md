# LIVE_NORMALIZED_FEATURE_PRODUCER_V1

## Purpose

Create the normalized live 5-minute checkpoint required by the audited shadow
strategy without duplicating the historical research semantics.

This module is built against the uploaded `feature/pcr-foundation` production tree.

## What V1 produces directly from existing `Snapshot`

At the latest exact snapshot timestamp:

- spot
- inferred strike interval
- moving ATM
- moving ATM +/-5 exact physical strikes
- exact CE and PE instrument keys at moving ATM
- 5-minute same-strike option OI comparison
- 10-minute same-strike option OI comparison
- 15-minute same-strike option OI comparison
- CE OI delta
- PE OI delta
- imbalance = PE delta - CE delta
- prior PCR
- current PCR
- PCR change
- per-horizon BULLISH / BEARISH / MIXED / NA
- BULLISH_ALL_3 / BEARISH_ALL_3 / MIXED / INCOMPLETE
- previous directional ALL_3
- snapshot data-health state and gating result

## Frozen ALL_3 semantics

For every horizon:

- BULLISH iff imbalance > 0 and PCR change > 0
- BEARISH iff imbalance < 0 and PCR change < 0
- MIXED otherwise when both are available
- NA when either is unavailable

ALL_3:

- all 5m/10m/15m BULLISH -> `BULLISH_ALL_3`
- all 5m/10m/15m BEARISH -> `BEARISH_ALL_3`
- any NA -> `INCOMPLETE`
- otherwise -> `MIXED`

## Exact-strike rule

The current moving ATM +/-5 physical strike basket is selected at T.

The SAME physical strikes are queried at:

- T-5
- T-10
- T-15

There is no nearest-strike substitution.

## Exact-time rule

Prior snapshots must exist at the exact requested timestamp.

There is no nearest-time substitution.

A missing exact horizon therefore produces `NA` and ALL_3 becomes `INCOMPLETE`.

## Production-tree limitation found

The current `Snapshot` collector contains option-chain OI and spot, but it does not
contain a normalized live NIFTY futures candle/OI stream.

Therefore futures OI is intentionally an explicit external dependency. The bridge
module accepts a separately produced `futures_oi_state` and converts the normalized
checkpoint into `CompletedFiveMinuteCheckpoint` for the shadow runtime adapter.

Do not fabricate futures OI from option OI.

## Data health

The producer calls `LIVE_OBSERVATIONAL_DATA_HEALTH_V1` before exposing the checkpoint.
Critical health states force the checkpoint to `INCOMPLETE`.

## Next step

After this module passes tests:

1. connect it to the live stored/collected Snapshot stream;
2. add a dedicated live NIFTY futures 1-minute/5-minute producer;
3. add exact option-minute OHLC acquisition for an open shadow observation;
4. run an integration replay;
5. enable observational live production.
