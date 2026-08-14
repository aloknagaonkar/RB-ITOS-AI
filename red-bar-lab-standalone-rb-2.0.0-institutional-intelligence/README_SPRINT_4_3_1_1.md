# Sprint 4.3.1.1 — Confirmed Swing Geometry Hardening

Fixes invalid output where:

- last swing high;
- last swing low;
- break level;
- invalidation level

could all display the same price.

## Changes

- confirmed pivot-high and pivot-low detection;
- left/right confirmation window;
- ATR-based minimum swing-distance validation;
- separate confirmed swing timestamps;
- breakout/breakdown only against confirmed prior pivots;
- structure score disabled when geometry is invalid;
- `STRUCTURE_UNAVAILABLE` or `STRUCTURE_DISTANCE_TOO_SMALL`;
- break and invalidation levels become `None` when invalid;
- UI table showing recent confirmed pivot candles.

## Files

- replacement `red_bar_lab/intelligence/stateful_multitimeframe_regime.py`
- replacement `red_bar_lab/ui/pages/shadow_directional_diagnostics.py`
- `red_bar_lab/tests/test_confirmed_swing_geometry.py`

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_stateful_multitimeframe_regime.py `
  red_bar_lab/tests/test_confirmed_swing_geometry.py -q
```

Execution remains blocked.
