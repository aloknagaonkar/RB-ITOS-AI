# LIVE_SHADOW_STEP_AUDIT_V1

Adds a separate append-only, hash-chained audit for every live-shadow processing step.

Every completed 5-minute checkpoint records:

1. `SNAPSHOT_SELECTION`
2. `NORMALIZED_FEATURES`
3. `DATA_HEALTH`
4. `ALL3_DECISION`
5. `CANDIDATE_DETECTION`

When a candidate progresses it also records:

6. `C2_ELIGIBILITY`
7. `FUTURES_FETCH`
8. `C2_DECISION`
9. `OPTION_RESOLUTION`
10. `ENTRY_OPEN`
11. one `OPTION_MINUTE` record for every processed completed 1-minute bar

`NORMALIZED_FEATURES` records exact 5m/10m/15m CE delta, PE delta, imbalance, current/prior PCR, PCR change, horizon state, moving ATM, exact strike basket, source receipt timestamp, source delay, health, and final ALL_3.

The existing `events.jsonl` remains the strategy lifecycle source of truth. `step-audit.jsonl` is the diagnostic/explainability source. No strategy thresholds or broker execution behavior are changed.
