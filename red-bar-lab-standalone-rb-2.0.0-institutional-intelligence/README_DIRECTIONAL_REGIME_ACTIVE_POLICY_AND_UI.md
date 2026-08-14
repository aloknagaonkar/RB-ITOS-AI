# Paper Trading — Directional Regime Active Policy + UI

Apply after the existing Directional Regime reference patch.

## Active decision policy

- `ALIGNED`: add `+5` to candidate score, capped at `100`.
- `CONFLICT`: place the signal on `HOLD`, expire its queue item, and stop before new candidate or paper-order creation.
- `PARTIAL_ALIGNMENT`: continue unchanged.
- `NEUTRAL`: continue unchanged.
- `UNAVAILABLE`: fail-open and continue with the existing Paper Trading signal.

Directional Regime Intelligence still cannot create a signal or trade by itself.

## Paper Trading UI

Adds a `Directional Regime Intelligence` section showing:

- status;
- regime;
- bundle direction;
- primary setup;
- alignment score;
- policy action;
- candidate bonus;
- reason;
- mode;
- bundle ID.

## Apply

```powershell
python .\apply_directional_regime_active_policy_and_ui.py
```

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_directional_regime_paper_reference.py `
  red_bar_lab/tests/test_directional_regime_active_policy.py -q
```
