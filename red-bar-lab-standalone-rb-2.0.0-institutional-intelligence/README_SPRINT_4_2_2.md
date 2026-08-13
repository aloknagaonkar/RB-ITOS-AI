# Sprint 4.2.2 — Shadow Directional UI and Observation Store

Copy the included files over the Sprint 4.2.1 deployment.

## UI

A new sidebar page appears:

`Shadow Directional`

The page:
- loads the selected day's 5-minute candles through the existing historical service;
- excludes the currently forming five-minute candle;
- evaluates the latest completed candle;
- shows direction, transition type, confidence, bullish/bearish score, regime,
  evidence, invalidation and Red Bar support;
- displays recent persisted history;
- always displays `Execution = BLOCKED`.

## Persistence

Observations are stored as JSONL under:

`artifacts/runs/shadow_directional/<instrument>.jsonl`

The exact root follows the project's configured `settings.runs_root`.

A duplicate instrument+candle timestamp is not inserted twice.

## Files

- `red_bar_lab/services/shadow_directional_store.py`
- `red_bar_lab/services/shadow_directional_observation.py`
- `red_bar_lab/ui/pages/shadow_directional_diagnostics.py`
- `red_bar_lab/ui/workspace.py`
- `red_bar_lab/tests/test_shadow_directional_store.py`

The Sprint 4.2.1 intelligence files must already be installed.

## Test

```powershell
$env:OPENBLAS_NUM_THREADS = "1"
$env:OMP_NUM_THREADS = "1"
python -m pytest red_bar_lab/tests/test_directional_features.py red_bar_lab/tests/test_directional_transition.py red_bar_lab/tests/test_shadow_directional_store.py -q
```

Restart Streamlit after copying the files.
