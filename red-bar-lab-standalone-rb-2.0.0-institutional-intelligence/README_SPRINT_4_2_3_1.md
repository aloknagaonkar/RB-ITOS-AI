# Sprint 4.2.3.1 — Shadow Candle Loading Fix

This patch fixes:

`Only 0 completed candles are available; at least 35 are required.`

## Cause

The Shadow Directional UI used `historical.read_day()`, which reads only an
existing local CSV. It did not call `load_or_download()` when the selected
5-minute candle file was missing.

## Fix

Both tabs now call `load_or_download()` before `read_day()`:

- Current Observation
- Historical Replay & Outcomes

For today's date, the service refreshes intraday 5-minute candles.
For a past date, it downloads historical 5-minute candles when needed.

## Install

Replace:

`red_bar_lab/ui/pages/shadow_directional_diagnostics.py`

Add:

`red_bar_lab/tests/test_shadow_directional_candle_loading.py`

Restart Streamlit after copying.

## Validate

```powershell
python -m pytest red_bar_lab/tests/test_shadow_directional_candle_loading.py -q
```
