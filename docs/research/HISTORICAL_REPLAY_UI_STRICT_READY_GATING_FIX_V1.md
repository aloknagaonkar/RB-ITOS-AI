# Historical Replay UI Strict-Ready Gating Fix V1

The backend strict readiness correctly blocked 2026-09-15 because only 60/74
exact checkpoints were available. However, the UI still derived its READY state
from the older nested readiness booleans, including
`full_replay_prerequisites_ready`, which was true.

That allowed the Run Replay button to be clicked, after which the backend
returned a strict-readiness 409 error.

This fix makes the UI consume the operations API's top-level
`strict_replay_ready` value. When that value is present, it is authoritative.
The older readiness booleans are only a compatibility fallback.

Result:
- 2026-09-15 shows NOT READY and Run Replay is disabled.
- 2026-09-17 shows READY after futures are available and 74/74 checkpoints are covered.
- No backend, strategy, replay, or execution behavior changes.
