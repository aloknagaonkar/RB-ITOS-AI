# Sprint 4.3.2 — Persistent Transition Sequence State Machine

Install over Sprint 4.3.1.1.

## Adds

- persistent bullish/bearish transition IDs;
- active, confirmed and invalidated transition status;
- monotonic stage progression;
- direction-change reset;
- transition start/update/confirm/invalidate timestamps;
- transition progress percentage;
- break and invalidation levels carried through the sequence;
- attribution seed IDs for future signal/candidate/opportunity/committee/trade links.

## UI

`Shadow Directional -> Stateful Regime v4.3`

New sections:

- Persistent Transition Sequence
- Attribution Seed

## Persistence

`artifacts/runs/transition_sequence_v43/<instrument>.jsonl`

## Attribution chain foundation

- regime_snapshot_id
- transition_id
- signal_id
- candidate_id
- opportunity_id
- committee_decision_id
- trade_id

Only the first two are populated in Sprint 4.3.2. Fresh Setup Engine will populate
`signal_id` in Sprint 4.3.3.

## Files

- `red_bar_lab/intelligence/transition_sequence_state_machine.py`
- `red_bar_lab/services/transition_sequence_store.py`
- `red_bar_lab/services/attribution_context.py`
- replacement `red_bar_lab/ui/pages/shadow_directional_diagnostics.py`
- `red_bar_lab/tests/test_transition_sequence_state_machine.py`

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_stateful_multitimeframe_regime.py `
  red_bar_lab/tests/test_confirmed_swing_geometry.py `
  red_bar_lab/tests/test_transition_sequence_state_machine.py -q
```

Execution remains blocked.
