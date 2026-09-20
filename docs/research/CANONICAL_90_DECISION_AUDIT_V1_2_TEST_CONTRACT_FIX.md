# Canonical 90 Decision Audit V1.2 Test Contract Fix

The V1 regression test still supplied a synthetic preclassified
`futures_oi_state` row.

V1.2 intentionally changed `load_futures()` to accept the real production
source contract: 1-minute futures candles containing `close` and
`open_interest`, from which exact completed 5-minute OI states are derived.

This patch changes only the stale V1 test fixture. It does not change
production decision logic and does not reintroduce a preclassified-state
fallback.
