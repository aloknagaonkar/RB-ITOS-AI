# DRI-Only Test Mode

This patch disables only new Reference-Level entries while you test DRI.

It keeps early 1-minute DRI, confirmed 5-minute DRI, Committee, queue, risk,
stop, trailing and exit processing enabled.

## Apply

```powershell
python .\apply_dri_only_test_mode.py
```

## Enable DRI-only mode

Set this in the same PowerShell session used to start the Paper Trading monitor:

```powershell
$env:RB_ENABLE_REFERENCE_LEVEL_SIGNALS = "false"
```

Then restart the monitor and Streamlit.

## Restore normal mode

```powershell
$env:RB_ENABLE_REFERENCE_LEVEL_SIGNALS = "true"
```

or:

```powershell
Remove-Item Env:RB_ENABLE_REFERENCE_LEVEL_SIGNALS
```

Restart the monitor after changing it.

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_dri_only_test_mode.py `
  red_bar_lab/tests/test_early_1m_directional_entry.py `
  red_bar_lab/tests/test_directional_regime_native_signal_merge.py -q
```
