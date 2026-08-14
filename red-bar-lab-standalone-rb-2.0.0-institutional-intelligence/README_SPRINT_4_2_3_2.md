# Sprint 4.2.3.2 — Index Volume Fallback Fix

Fixes:

`ValueError: Insufficient completed candle history for directional features: volume_ratio`

## Cause

NIFTY index candles can contain zero or unavailable volume. The original feature
builder divided the current volume by a rolling volume average and treated a
missing ratio as a fatal feature error.

## Fix

- Volume remains supporting evidence only.
- A zero, unavailable or non-finite volume ratio becomes the neutral value `1.0`.
- `volume_ratio` no longer blocks creation of the directional snapshot.
- Price structure, EMA, ATR, DMI, ADX and displacement requirements remain strict.

## Install

Replace:

`red_bar_lab/intelligence/directional_features.py`

Add:

`red_bar_lab/tests/test_directional_volume_fallback.py`

Restart Streamlit after copying.

## Validate

```powershell
python -m pytest red_bar_lab/tests/test_directional_volume_fallback.py -q
```
