# LIVE SHADOW PROD COMPAT + DATA HEALTH V1

This patch was prepared against the uploaded `feature/pcr-foundation` production tree.

## Confirmed production facts

- `ShadowEngine.detect()` expects `candle1_timestamp`.
- The previous adapter incorrectly passed `all3_candle1_timestamp`.
- `worker.py` is currently a snapshot collector. It collects a `Snapshot` and stores it through
  `record(engine, config_id, snapshot)`.
- `Snapshot` already exposes useful health metadata:
  - `started_at`
  - `received_at`
  - `spot_feed_at`
  - `oi_source_at`
  - per-quote `quote_timestamp`
  - OI/LTP coverage
- `storage.py` already has worker-level heartbeat health, but that is collector process health,
  not market-data quality health.
- The uploaded production tree does not show a direct live ALL_3 + futures-OI orchestration path
  inside `worker.py`; those calculations currently exist primarily in research/audit modules.

## Patch contents

1. Production-compatible runtime adapter V1.1.
2. Data health evaluator V1.
3. Unit tests.
4. No broker execution.
5. No patch to `worker.py`.

## Why worker.py is not patched yet

Patching the collector would be premature because the shadow adapter needs normalized values that
the collector itself does not currently produce:

- completed 5m/10m/15m ALL_3
- prior directional ALL_3
- futures OI state at C2
- exact ATM option instrument
- exact next-minute option open
- completed 1-minute option OHLC after entry

The next integration task is therefore to identify/build the live normalized feature producer, then
wire the adapter there.

## Data-health gate

The health layer uses the existing Snapshot timestamps and quote fields.

Critical states fail closed:

- STALE
- MISSING
- OUT_OF_ORDER
- UNHEALTHY

DEGRADED is recorded but does not automatically block in V1.

No thresholds are strategy thresholds; they are operational freshness defaults and should be
reviewed against live provider latency before production enforcement.
