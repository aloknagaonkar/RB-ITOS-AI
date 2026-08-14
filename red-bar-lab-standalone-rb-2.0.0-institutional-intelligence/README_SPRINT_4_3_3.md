# Sprint 4.3.3 — Fresh Setup Signal Engine

Install over Sprint 4.3.2.

## New capability

The stateful regime and transition sequence now generate independent setup
signals with unique signal IDs.

## Setup types

- BULLISH_STRUCTURE_BREAK
- BEARISH_STRUCTURE_BREAK
- BULLISH_EMA_RECLAIM
- BEARISH_EMA_LOSS
- BULLISH_RANGE_BREAKOUT
- BEARISH_RANGE_BREAKDOWN
- BULLISH_PULLBACK_CONTINUATION
- BEARISH_PULLBACK_CONTINUATION
- BULLISH_RED_BAR_CONFIRMATION
- BEARISH_RED_BAR_CONFIRMATION
- COUNTER_TREND_RED_BAR

## Signal fields

- signal_id
- regime_snapshot_id
- transition_id
- setup_type
- direction
- detected_at
- trigger_level
- invalidation_level
- fresh_until
- primary_trigger
- supporting_evidence
- red_bar_alignment
- status
- execution_allowed=False

## Persistence

`artifacts/runs/fresh_setup_signals_v43/<instrument>.jsonl`

## UI

`Shadow Directional -> Stateful Regime v4.3`

New sections:

- Fresh Setup Signals
- Signal Attribution
- Generated Signals by Type
- Recent Fresh Setup History

## Files

- `red_bar_lab/intelligence/fresh_setup_signal_engine.py`
- `red_bar_lab/services/fresh_setup_signal_store.py`
- `red_bar_lab/services/signal_attribution.py`
- replacement `red_bar_lab/ui/pages/shadow_directional_diagnostics.py`
- `red_bar_lab/tests/test_fresh_setup_signal_engine.py`

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_transition_sequence_state_machine.py `
  red_bar_lab/tests/test_fresh_setup_signal_engine.py -q
```

Execution remains blocked. Sprint 4.3.4 will connect these signal IDs to
candidate, opportunity, committee and paper-trade attribution records.
