# RB-1.3.2 — Performance Stabilization

Performance-only release. No strategy thresholds, candidate scoring formulas, Primary/Shadow authority, expectancy, lifecycle, queue, stop/target, sizing, or exit behavior were changed.

## Changes

1. **Database initialization guard**
   - `RedBarDatabase.initialize()` still checks the DB path on every call.
   - Schema/migration/backfill work runs once per database instance during normal operation.
   - If the SQLite file is deleted, initialization runs again and recreates the schema (self-heal preserved).
   - Initialization is protected by an instance lock.

2. **Paper Trading batch reads**
   - Added `read_signal_attempts_by_ids()`.
   - Added `read_execution_state_events_for_signals()`.
   - Trade Lifecycle/Provenance, Open Positions, and Journal reuse batched signal metadata instead of N+1 per-row lookups.
   - Lifecycle events are batch-loaded only when the lazy lifecycle panel is enabled.

3. **Upstox HTTP connection reuse**
   - `UpstoxClient` now owns/reuses a `requests.Session`.
   - Optional injected session keeps tests/adapters controllable.
   - HTTP endpoint, payload, timeout, authentication, and response handling remain unchanged.

4. **Concurrent candidate candle retrieval**
   - Independent option-candle validation for the candidate set is fetched with a bounded `ThreadPoolExecutor` (max 5 workers).
   - Candidate scoring and final sort remain sequential and unchanged after all candle results are available.
   - Per-candidate fetch failures preserve the existing unavailable-candle behavior.

## Verification

- Full regression suite: **220 passed**.
- Added tests for DB self-heal, batch/single read parity, concurrent candle retrieval, and reusable Upstox HTTP session.
- Local SQLite hot-path microbenchmark (100 `health()` calls after first initialization):
  - RB-1.3.1 baseline: ~215 ms
  - RB-1.3.2: ~52 ms
  - ~4.1x faster in this synthetic DB hot-path check.

Actual end-to-end improvement depends on broker latency, trade-history size, and which Paper Trading sections are visible. Candidate candle retrieval should benefit most when multiple broker requests are slow, because independent requests now overlap instead of waiting serially.
