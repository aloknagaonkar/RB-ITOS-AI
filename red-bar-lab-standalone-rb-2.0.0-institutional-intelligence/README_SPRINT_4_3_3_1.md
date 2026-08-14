# Sprint 4.3.3.1 — Signal Identity and Setup Bundling

Install over Sprint 4.3.3.

## Fixes

- signal IDs are deterministic;
- repeated evaluation returns the canonical persisted signal record;
- multiple simultaneous setups are grouped into one bundle;
- one primary trigger is selected;
- remaining setups are preserved as supporting signals;
- one bundle is persisted per transition timestamp.

## Primary-trigger priority

1. Structure break
2. Range breakout/breakdown
3. Pullback continuation
4. EMA reclaim/loss
5. Red Bar confirmation
6. Counter-trend Red Bar

## Persistence

Signals:

`artifacts/runs/fresh_setup_signals_v43/<instrument>.jsonl`

Bundles:

`artifacts/runs/fresh_setup_bundles_v43/<instrument>.jsonl`

## Files

- replacement `red_bar_lab/intelligence/fresh_setup_signal_engine.py`
- replacement `red_bar_lab/services/fresh_setup_signal_store.py`
- `red_bar_lab/services/fresh_setup_bundle.py`
- `red_bar_lab/services/fresh_setup_bundle_store.py`
- replacement `red_bar_lab/ui/pages/shadow_directional_diagnostics.py`
- `red_bar_lab/tests/test_signal_identity_and_bundling.py`

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_fresh_setup_signal_engine.py `
  red_bar_lab/tests/test_signal_identity_and_bundling.py -q
```

Execution remains blocked. Sprint 4.3.4 can now safely link one setup bundle to
candidate, opportunity, committee decision and paper trade.
