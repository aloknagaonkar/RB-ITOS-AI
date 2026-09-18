# Historical Replay Hardening V1.1

Adds arbitrary date selection, readiness-first gating, explicit availability semantics,
active-job recovery after browser refresh, stale-job recovery, and explicit overwrite wording.

No strategy logic is changed. Live execution and paper orders remain disabled.

Availability semantics:
- AVAILABLE: usable locally.
- DOWNLOADABLE: current pipeline can fetch the missing dataset.
- NOT_DOWNLOADABLE: historical option-chain OI snapshots must already exist locally.
- ON_DEMAND: exact option 1-minute data is resolved only after causal option selection.

The UI must not imply every past date is replayable. Date entry is unrestricted;
readiness determines whether replay can actually run.
