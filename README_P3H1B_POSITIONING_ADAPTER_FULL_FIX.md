# P3H.1b Full positioning adapter fix

The previous hotfix package contained patch instructions only, so simply copying the bundle did not replace the actual Python module.

This bundle contains the full corrected module:

`backend/market_lab/historical_positioning_adapter_v1.py`

Replace the existing file with this one and rerun:

```bash
python -m pytest tests/test_p3h1_positioning_cache_adapter_v1.py -v
```

Expected: `2 passed`.
