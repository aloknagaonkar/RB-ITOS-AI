# Sprint 4.3.4 — Signal-to-Trade Attribution Ledger

Install over Sprint 4.3.3.1.

## Purpose

Links one setup bundle to the complete pipeline:

`Bundle -> Candidate -> Opportunity -> Committee -> Paper Trade -> Exit -> Outcome`

## Attribution fields

- ledger_id
- regime_snapshot_id
- transition_id
- bundle_id
- primary_signal_id
- primary_setup_type
- supporting signal IDs and setup types
- candidate ID/status/time
- opportunity ID/status/time
- Committee decision ID/result/reason/time
- trade ID/mode/CE-or-PE/symbol
- entry and exit
- realized P&L and percentage
- MFE and MAE
- target/stop flags
- exit reason
- SUCCESS / FAILURE / BREAKEVEN / other terminal outcome

## UI

`Shadow Directional -> Stateful Regime v4.3`

New sections:

- Signal-to-Trade Attribution Ledger
- Attribution Funnel
- Success by Primary Signal Type
- Recent Attributed Trades and Outcomes

## Persistence

`artifacts/runs/signal_trade_attribution_v43/<instrument>.jsonl`

## Existing pipeline integration

Use `apply_pipeline_event()` with normalized events:

- CANDIDATE
- OPPORTUNITY
- COMMITTEE
- TRADE_ENTRY
- TRADE_EXIT

This package creates the ledger and adapter. Actual project-specific event hooks
can call the adapter where candidates, opportunities, Committee decisions and
paper trades are already created.

## Files

- `red_bar_lab/services/signal_trade_attribution.py`
- `red_bar_lab/services/signal_trade_attribution_store.py`
- `red_bar_lab/services/signal_trade_attribution_summary.py`
- `red_bar_lab/services/signal_trade_pipeline_adapter.py`
- replacement `red_bar_lab/ui/pages/shadow_directional_diagnostics.py`
- `red_bar_lab/tests/test_signal_trade_attribution.py`

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_signal_identity_and_bundling.py `
  red_bar_lab/tests/test_signal_trade_attribution.py -q
```

Execution remains blocked for the v4.3 engine.
