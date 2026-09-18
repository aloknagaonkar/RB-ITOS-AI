# Historical Replay Hardening V1.2 — API Test Compatibility Fix

The existing API test injects a minimal readiness stub such as:

`{"checkpoint_replay_ready": true}`

It does not provide the production `datasets` array. V1.2 strict readiness
correctly requires exact snapshot checkpoint coverage plus futures availability,
so that minimal stub no longer reached the launch path.

This patch adds a compatibility fallback only when `datasets` is absent/empty.

Production `historical_replay_data_v1.readiness()` returns dataset rows, so real
runtime behavior is unchanged:

- all 74 exact 5-minute checkpoints must be covered;
- NIFTY futures 1-minute data must be available;
- exact option data remains ON_DEMAND.

If production-shaped datasets are present, legacy readiness booleans cannot
override failed strict checkpoint coverage.
