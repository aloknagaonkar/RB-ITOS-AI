# Sprint 4.3.4.1 — Existing Pipeline Attribution Hooks

Install over Sprint 4.3.4.

## Concrete integration points

The active Paper Trading runtime uses `TrendAwarePaperAutomationService`, whose
parent `RedBarPaperAutomationService.process_new_signals()` owns:

- candidate scoring and trade-selection persistence;
- opportunity evaluation;
- Institutional Execution Committee evaluation;
- execution queue persistence;
- paper option entry.

This package replaces the runtime service reference with
`AttributionAwarePaperAutomationService`. The existing workflow runs first and
remains the only execution authority. After it completes, an observational
reconciler links the persisted pipeline records to the nearest compatible v4.3
setup bundle.

## Matching rule

Because v4.3 remains shadow-only and does not submit the legacy Red Bar signal
into execution, the bridge records:

- same direction;
- event within the bundle freshness window plus a 45-minute reconciliation
  grace period;
- candidate symbol/instrument continuity after the first match.

The ledger records:

- `pipeline_signal_id`;
- `pipeline_match_method = DIRECTION_AND_FRESHNESS_WINDOW`.

This is explicitly comparative attribution, not proof that v4.3 caused the
legacy trade.

## Linked events

- candidate selection;
- opportunity evaluation;
- Committee decision;
- paper trade entry;
- paper trade close/outcome;
- realized P&L, MFE, MAE and exit reason when available.

## Files

- `red_bar_lab/services/attribution_pipeline_reconciler.py`
- `red_bar_lab/execution/attribution_automation.py`
- replacement `red_bar_lab/ui/workspace.py`
- `red_bar_lab/tests/test_existing_pipeline_attribution_hooks.py`

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_signal_trade_attribution.py `
  red_bar_lab/tests/test_existing_pipeline_attribution_hooks.py -q
```

Then run the normal paper decision cycle. The v4.3 attribution dashboard will
populate on the next cycle when a same-direction legacy pipeline event falls
inside the setup bundle window.

## Safety

- no candidate is created by v4.3;
- no Committee decision is changed;
- no queue status is changed;
- no paper order is opened or closed by the reconciler;
- `execution_allowed` remains false.
