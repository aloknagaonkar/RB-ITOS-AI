# Early 1-Minute Directional Entry

This incremental patch allows a completed 1-minute structure break to create a
short-lived native DRI signal before the 5-minute regime becomes fully aligned.

Rules:

- confirmed 1-minute swing break required;
- EMA10/EMA30, EMA slope, momentum and displacement candle must agree;
- strongly opposite 5-minute regime blocks the signal;
- SIDEWAYS or same-direction 5-minute state is allowed;
- signal freshness is four minutes;
- only Rank 1 candidate is executable;
- normal Committee, queue, position and exit controls remain active;
- later same-direction 5-minute confirmation is reinforcement only.

## Apply

```powershell
python .\apply_early_1m_directional_entry.py
```

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_early_1m_directional_entry.py `
  red_bar_lab/tests/test_directional_regime_background_cycle.py `
  red_bar_lab/tests/test_directional_regime_native_signal_merge.py -q
```
