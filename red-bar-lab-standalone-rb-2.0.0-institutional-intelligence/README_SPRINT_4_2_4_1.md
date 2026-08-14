# Sprint 4.2.4.1 — Candle Loading Test Compatibility Fix

Sprint 4.2.4 refactored candle loading into the shared `_load_day()` helper.

The old regression test searched for inline `load_or_download()` calls beside
`selected_date` and `replay_date`, so it failed even though the application
still loads/downloads candles before reading them.

Replace:

`red_bar_lab/tests/test_shadow_directional_candle_loading.py`

Then run:

```powershell
python -m pytest red_bar_lab/tests/test_shadow_directional_candle_loading.py -q
python -m pytest -q
```

No production code changes are required.
