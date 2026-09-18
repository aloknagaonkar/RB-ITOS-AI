# Historical Replay UI API V1 Fix1

The original V1 functions captured `REPLAY_ROOT` as a Python default argument at
module import time. Pytest monkeypatched `api.REPLAY_ROOT`, but `_session_dir()`
and `list_sessions()` continued using the original production path.

That is why the tests saw the real 2026-09-18 replay:
- observation_count = 8 instead of fixture value 1
- timeline rows = 74 instead of fixture value 1

Fix1 changes the two function defaults to `None` and reads the current module-level
`REPLAY_ROOT` at call time. No API shape, replay data, strategy logic, or production
files are changed.
