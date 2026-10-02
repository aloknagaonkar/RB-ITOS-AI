# Canonical 90 Decision Audit V1.1 — Real Schema + Population Fix

Two issues were found from the real enriched run:

1. Real enriched rows use:
   `moving_horizons["5m"]`, `["10m"]`, `["15m"]`
   while V1 only checked `"5"`, `"10"`, `"15"`.
   Result: every horizon appeared missing and events stayed at zero.

2. V1 scanned every enriched directory, which included newly-built
   2026-09-09/10/11 dates in addition to the frozen canonical 90.
   Result: 93 sessions / 6882 checkpoints instead of 90 / 6660.

V1.1:
- reads real `5m/10m/15m` keys, retaining compatibility with old test forms;
- loads the exact canonical date set from the frozen canonical CSV;
- filters enriched sessions to those dates only;
- adds regression tests for both problems.

No strategy thresholds or ALL_3 rules are changed.
