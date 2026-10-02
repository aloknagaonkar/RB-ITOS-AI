# Historical OI Cache Reuse Wrapper Compatibility Fix V1

Root cause:
- the cache-reuse finder correctly found the legacy historical-positioning cache;
- the legacy cache stores a single session at the JSON top level;
- `_load_built()` expects the newer build-wrapper format with a `sessions` array;
- therefore reuse failed with `Expected exactly one built session ... found 0`.

Fix:
- add `_load_session_compatible()`;
- support both wrapper and legacy single-session JSON formats;
- use the compatible loader for Phase A and final/wider source loading.

No calculation logic, expiry logic, strategy rules, or canonical data are changed.
