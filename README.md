# Hilega Directional Live Shadow v1 patch

Adds isolated observation-only directional live wiring.

Files:
- `backend/market_lab/hilega_directional_live_shadow_v1.py` (new)
- `backend/market_lab/hilega_directional_coordinator_v1.py` (adds exact 14:55 cutoff coordination)
- `backend/market_lab/live_shadow_worker_v1.py` (adds `HILEGA_DIRECTIONAL_SHADOW_V1` selector)
- `tests/test_hilega_directional_live_shadow_v1.py` (new)
- documentation

Validated against the current source snapshot: 48 tests passed and worker import passed.

No strategy-rule changes. No UI changes. No execution/paper-order capability.
