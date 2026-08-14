# Sprint 4.2.7 — Regime and Period Stability Analysis

Install over Sprint 4.2.6.

## New UI

`Shadow Directional -> Regime & Period Stability`

## Purpose

Explains why calibration performance changed out of sample without modifying
the engine.

## Analysis

- calibration vs out-of-sample 5m/15m/30m accuracy;
- MFE/MAE and ratio comparison;
- weekly stability;
- performance by regime;
- bullish vs bearish performance;
- time-of-day performance;
- volatility-bucket performance;
- consecutive 30-minute failure clusters;
- same-direction signal density inside a configurable cooldown window;
- downloadable row-level CSVs for both periods.

## Findings

Possible findings include:

- `PERIOD_ACCURACY_DECAY`
- `OOS_ADVERSE_MOVE_DOMINATES`
- `HIGH_CONSECUTIVE_SIGNAL_DENSITY`
- `CONSECUTIVE_FAILURE_CLUSTER`

## Files

- `red_bar_lab/services/shadow_regime_period_stability.py`
- replacement `red_bar_lab/ui/pages/shadow_directional_diagnostics.py`
- `red_bar_lab/tests/test_shadow_regime_period_stability.py`

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_shadow_regime_period_stability.py `
  red_bar_lab/tests/test_shadow_directional_candle_loading.py -q
```

No thresholds, weights or execution behavior are changed.
