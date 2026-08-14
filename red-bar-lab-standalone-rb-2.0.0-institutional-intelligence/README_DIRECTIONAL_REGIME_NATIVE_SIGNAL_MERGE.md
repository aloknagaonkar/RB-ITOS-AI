# Directional Regime Native Signal + 10-Minute Merge

This combined package includes the earlier active confirmation policy and Paper
Trading UI patch, plus the independent native signal adapter.

## Behavior

- A fresh BULLISH bundle becomes a native BULLISH Paper Trading signal and uses
  the normal CE candidate, opportunity, Committee, queue and paper-order flow.
- A fresh BEARISH bundle becomes a native BEARISH signal and uses the PE flow.
- Same instrument and direction within 10 minutes merges into one opportunity.
- Opposite directions within 10 minutes are not exposed for execution.
- A same-direction open position receives reinforcement only; no second order.
- An opposite open position must exit/review first; no hedge is opened.
- `DRI-{bundle_id}` prevents repeated execution from the same bundle.
- Expired, SIDEWAYS, CONFLICT and transition-only bundles cannot execute.
- Historical v4.3 records remain unchanged with `execution_allowed=False`; the
  Paper Trading adapter creates a separate executable row only at runtime.

## Apply

```powershell
python .\apply_directional_regime_native_signal_merge.py
```

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_directional_regime_paper_reference.py `
  red_bar_lab/tests/test_directional_regime_active_policy.py `
  red_bar_lab/tests/test_directional_regime_native_signal_merge.py -q
```

Restart Streamlit and the background Paper Trading monitor after applying.
