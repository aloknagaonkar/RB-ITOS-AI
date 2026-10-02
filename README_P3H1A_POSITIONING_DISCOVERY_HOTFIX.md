# P3H.1a positioning discovery hotfix

Root cause:
`discover_positioning_sessions()` required filenames matching
`NSE_INDEX_Nifty_50__*.json`, while the unit test intentionally used
`later.json` and `near.json`.

Fix:
Discover all `.json` files under `historical-positioning-cache*` directories
and validate `session_date` from file contents instead of depending on filename.

Apply by replacing only `discover_positioning_sessions()` in:

`backend/market_lab/historical_positioning_adapter_v1.py`

Then run:

```bash
python -m pytest tests/test_p3h1_positioning_cache_adapter_v1.py -v
```
