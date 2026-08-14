# DRI Committee Red Bar Source Fix

Paper Trading previously calculated `opposite_red_bar` by searching for any
newer opposite-direction signal. That legacy rule was incorrectly applied to
DRI even when `red_bar_alignment=NOT_AVAILABLE`.

## New behavior

DRI:
- NOT_AVAILABLE / UNAVAILABLE / NEUTRAL / ALIGNED -> no blocker
- OPPOSITE / CONFLICT / explicit opposite direction -> blocker

Reference-Level:
- existing newer opposite Reference-Level rule is preserved

## Apply

```powershell
python .\apply_dri_committee_red_bar_source_fix.py
```

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_dri_committee_red_bar_source.py `
  red_bar_lab/tests/test_dri_structure_and_active_top.py `
  red_bar_lab/tests/test_directional_regime_native_signal_merge.py -q
```

Restart Streamlit and the Paper Trading monitor. Existing records do not change;
validate with a new DRI signal.
