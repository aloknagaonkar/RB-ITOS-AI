# Historical Replay Hardening V1.2 — Strict Readiness

Runtime testing exposed two issues:

1. `NIFTY_FUTURES_1M` was lower-cased to `nifty_futures_1m`, but V1.1 did not
   recognize that exact production name, so a missing cache remained `MISSING`
   instead of becoming `DOWNLOADABLE`.

2. A non-zero snapshot count is not enough. A partial day can have snapshots but
   still be unusable for causal replay from 09:20.

Strict readiness now verifies all 74 expected 5-minute checkpoints from 09:20
through 15:25. Each checkpoint requires the first stored snapshot at or after the
checkpoint within +30 seconds, matching replay selection semantics.

Replay is enabled only when all 74 checkpoints are covered and futures 1-minute
data is available. Exact option 1-minute data remains ON_DEMAND.
