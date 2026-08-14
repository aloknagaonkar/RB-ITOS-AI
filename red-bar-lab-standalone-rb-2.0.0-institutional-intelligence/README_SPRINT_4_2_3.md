# Sprint 4.2.3 — Shadow Outcomes and Historical Replay

Install over Sprint 4.2.1 and Sprint 4.2.2.

## Adds

- future prices after 5, 15 and 30 minutes;
- direction-normalized movement;
- MFE and MAE;
- accuracy at 5, 15 and 30 minutes;
- false-transition rate at 30 minutes;
- performance grouped by market regime;
- comparison with the nearest same-direction current-engine confirmation;
- shadow lead or lag in minutes;
- Historical Replay & Outcomes tab in the Shadow Directional UI.

## Files

- `red_bar_lab/services/shadow_directional_outcome.py`
- `red_bar_lab/services/shadow_directional_replay.py`
- `red_bar_lab/services/shadow_directional_comparison.py`
- replacement `red_bar_lab/ui/pages/shadow_directional_diagnostics.py`
- tests for outcome, replay and comparison

## Validation

```powershell
$env:OPENBLAS_NUM_THREADS = "1"
$env:OMP_NUM_THREADS = "1"
$env:MKL_NUM_THREADS = "1"
$env:NUMEXPR_NUM_THREADS = "1"

python -m pytest `
  red_bar_lab/tests/test_directional_features.py `
  red_bar_lab/tests/test_directional_transition.py `
  red_bar_lab/tests/test_shadow_directional_store.py `
  red_bar_lab/tests/test_shadow_directional_outcome.py `
  red_bar_lab/tests/test_shadow_directional_replay.py -q
```

Restart Streamlit and open:

`Shadow Directional -> Historical Replay & Outcomes`

Execution remains permanently blocked.
