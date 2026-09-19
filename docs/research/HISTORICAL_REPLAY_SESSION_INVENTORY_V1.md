# Historical Replay Session Inventory V1

Adds a read-only inventory of historical dates.

- STRICT_READY: 74/74 checkpoints within +30 seconds.
- LEGACY_COMPATIBLE: not strict, but 74/74 within +65 seconds.
- PARTIAL: some snapshots exist but even +65 seconds is incomplete.
- UNAVAILABLE: zero stored option-chain snapshots.

Futures availability is shown separately. This patch does not enable legacy replay and does not weaken strict replay.
