# Sprint 4.2.8 — Cooldown, Deduplication and Confirmation Simulation

Install over Sprint 4.2.7.

## New UI

`Shadow Directional -> Lifecycle Simulation`

## Simulated controls

- baseline;
- 15/30/45/60-minute same-direction cooldown;
- one signal per directional move;
- 30/60-minute lockout after a failed 30-minute outcome;
- combined one-move + 30m cooldown + 60m failure lockout;
- breakout-hold confirmation;
- pullback/retest confirmation.

## Comparison metrics

- accepted and suppressed signals;
- 5m/15m/30m accuracy;
- false rate;
- average MFE and MAE;
- MFE/MAE ratio;
- maximum consecutive failures;
- duplicate signal percentage;
- performance by regime;
- performance by time of day;
- suppression reason counts;
- accepted/suppressed CSV export.

## Files

- `red_bar_lab/services/shadow_signal_lifecycle_simulation.py`
- replacement `red_bar_lab/ui/pages/shadow_directional_diagnostics.py`
- `red_bar_lab/tests/test_shadow_signal_lifecycle_simulation.py`

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_shadow_signal_lifecycle_simulation.py `
  red_bar_lab/tests/test_shadow_directional_candle_loading.py -q
```

All results remain historical and observation-only.
