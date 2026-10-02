# Historical Replay Operations V1.2 Integration

This patch changes only the replay runner used by the background Replay
Operations worker:

- old: `historical_replay_day_v1_1.run_day`
- new: `historical_replay_day_v1_2.run_day`

No live-shadow strategy code is modified.

The switch is permitted only after V1.2 parity has passed against the preserved
V1.1 baseline. For 2026-09-18 the verified parity target is:

- 74/74 checkpoints
- 0 missing
- 8 observations
- 3 CLOSED / 5 REJECTED
- 39 event rows
- 74 health rows
- 418 step-audit rows
- identical trades
- identical event semantics
- identical health
- identical step-audit semantics
- valid audit chain

After applying, restart services and launch one replay through the operations API.
The expected runtime should be on the order of tens of seconds rather than the
~10 minute V1.1 baseline.
