# Sprint 4.3.1 — Stateful Multi-Timeframe Regime Engine

Install over Sprint 4.2.8.

## Combined architecture

Sprint 4.2 remains the research, replay and validation framework.

Sprint 4.3 begins the target directional architecture:

- completed 5-minute regime;
- completed 1-minute early-transition structure;
- bullish and bearish scores;
- stateful previous/current regime;
- transition stage and progress;
- swing, break and invalidation levels;
- Red Bar as supporting evidence only;
- append-only persisted history;
- execution permanently blocked.

## New UI

`Shadow Directional -> Stateful Regime v4.3`

## Files

- `red_bar_lab/intelligence/stateful_multitimeframe_regime.py`
- `red_bar_lab/services/stateful_regime_store.py`
- replacement `red_bar_lab/ui/pages/shadow_directional_diagnostics.py`
- `red_bar_lab/tests/test_stateful_multitimeframe_regime.py`

## Validate

```powershell
python -m pytest red_bar_lab/tests/test_stateful_multitimeframe_regime.py -q
```

This is Sprint 4.3.1 only. The next package will add the persistent transition
sequence state machine and independent Fresh Setup Engine.
