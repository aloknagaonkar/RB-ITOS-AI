# Directional Bundle Primary-Signal Join Fix

The normal v4.3 bundle stores `primary_signal_id`, while freshness and execution
levels stay on the corresponding Fresh Setup Signal.

The earlier Paper Trading adapter looked only at the bundle and rejected it when
`fresh_until` was absent.

This patch joins:

```text
fresh_setup_bundles_v43.primary_signal_id
→ fresh_setup_signals_v43.signal_id
```

and inherits freshness, trigger, invalidation, setup type and direction.

## Apply

```powershell
python .\apply_directional_bundle_primary_signal_join_fix.py
```

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_directional_bundle_primary_signal_join.py `
  red_bar_lab/tests/test_early_1m_directional_entry.py `
  red_bar_lab/tests/test_directional_regime_native_signal_merge.py -q
```

Restart Streamlit and the Paper Trading monitor.
