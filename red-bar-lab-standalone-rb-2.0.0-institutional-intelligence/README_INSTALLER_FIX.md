# Directional Regime Installer Fix

The previous installer searched only for `def render(`. The current Paper
Trading page uses `def render_page(`.

Copy both replacement installer files into the project root and overwrite the
existing copies. Then run:

```powershell
python .\apply_directional_regime_native_signal_merge.py
```

The corrected active-policy installer also tolerates the earlier partial backend
installation.

Validate with:

```powershell
python -m pytest `
  red_bar_lab/tests/test_directional_regime_paper_reference.py `
  red_bar_lab/tests/test_directional_regime_active_policy.py `
  red_bar_lab/tests/test_directional_regime_native_signal_merge.py -q
```
