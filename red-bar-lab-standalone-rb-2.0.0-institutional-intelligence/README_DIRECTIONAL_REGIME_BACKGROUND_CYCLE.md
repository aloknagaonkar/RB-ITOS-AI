# Automatic Directional Regime Background Cycle

This incremental patch removes the need to click **Evaluate stateful regime**
before every Paper Trading cycle.

The background sequence is:

`completed 1m/5m candles → regime → transition → signals → bundle → native DRI`

The refresh runs before the normal Paper Trading signal scan. It is fail-open:
provider or data errors do not stop the existing Reference-Level pipeline.

Apply:

```powershell
python .\apply_directional_regime_background_cycle.py
```

Validate:

```powershell
python -m pytest `
  red_bar_lab/tests/test_directional_regime_background_cycle.py `
  red_bar_lab/tests/test_directional_regime_paper_reference.py `
  red_bar_lab/tests/test_directional_regime_active_policy.py `
  red_bar_lab/tests/test_directional_regime_native_signal_merge.py -q
```

Restart Streamlit and the Paper Trading background monitor.
