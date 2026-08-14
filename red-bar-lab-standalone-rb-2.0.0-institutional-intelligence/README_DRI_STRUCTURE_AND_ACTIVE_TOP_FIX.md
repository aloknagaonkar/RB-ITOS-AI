# DRI Structure and Active Top Fix

Active Top now shows only eligible candidates connected to a currently active
execution queue item. Stale rankings and duplicate contract rows are hidden.

DRI structure validation now uses the DRI trigger and invalidation levels.
For bearish DRI, structure remains valid until spot rises above invalidation.
For bullish DRI, structure remains valid until spot falls below invalidation.

Red Bar remains supporting evidence for DRI:
- NOT_AVAILABLE is non-blocking.
- Explicit opposite/conflicting alignment still blocks.

This does not bypass Committee; it corrects the evidence sent to Committee.

## Apply

```powershell
python .\apply_dri_structure_and_active_top_fix.py
```

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_dri_structure_and_active_top.py `
  red_bar_lab/tests/test_directional_bundle_primary_signal_join.py `
  red_bar_lab/tests/test_early_1m_directional_entry.py `
  red_bar_lab/tests/test_directional_regime_native_signal_merge.py -q
```

Restart Streamlit and the Paper Trading monitor.
