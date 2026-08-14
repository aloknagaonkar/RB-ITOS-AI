# Sprint 4.2.5 — Feature Contribution and Threshold Calibration

Install over Sprint 4.2.4.1.

## New UI

`Shadow Directional -> Feature Calibration`

Default research filter:

`STRONG_SHADOW_SIGNAL`

## Analysis

- raw EMA fast/slow slope;
- EMA acceleration and spread;
- ADX and ADX slope;
- absolute and direction-normalized DMI gap;
- raw and direction-normalized ATR displacement;
- range and compression;
- direction and regime;
- breakout/breakdown and structure flags;
- time-of-day buckets;
- individual evidence tags;
- evidence-tag pairs;
- 30-minute accuracy lift against baseline;
- MFE/MAE and MFE-to-MAE ratio;
- research-only calibration recommendations;
- downloadable row-level calibration CSV.

## Important guardrail

No weight or threshold is automatically changed. Recommendations must be
verified on a separate out-of-sample date range before any engine modification.

## Files

- `red_bar_lab/services/shadow_feature_calibration.py`
- replacement `red_bar_lab/ui/pages/shadow_directional_diagnostics.py`
- `red_bar_lab/tests/test_shadow_feature_calibration.py`
- refreshed `red_bar_lab/tests/test_shadow_directional_candle_loading.py`

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_shadow_feature_calibration.py `
  red_bar_lab/tests/test_shadow_directional_candle_loading.py -q
```

Execution remains blocked.
