# Sprint 4.3.5.1 — Range Historical Audit and Matching

Install over the current `main` branch.

## Adds

A new Shadow Directional tab:

`Historical Attribution Replay`

This first historical replay phase is deliberately audit-only.

## Range support

- Single day
- Previous 5 trading days
- Previous 10 trading days
- Previous month
- Previous 3 months
- Custom range
- Maximum 90 calendar days per run

## Session support

- Full session
- Opening
- Mid-session
- Closing
- Custom start/end time

## Filters

- direction
- primary v4.3 setup type

## Sources audited

- v4.3 setup bundles
- signal attempts
- trade selection evaluations
- opportunity evaluations
- institutional Committee evaluations
- execution queue
- paper execution orders

## Match methods

- `EXACT_SIGNAL_ID`
- `DIRECTION_AND_WINDOW`
- `NO_MATCH`

Exact identifiers are treated as direct evidence. Direction/time matching is
explicitly labelled as inferred alignment.

## Safety

This package does not:

- run paper automation;
- create candidates;
- create opportunity evaluations;
- invoke Committee logic;
- create queue records;
- enter or close paper positions;
- call live execution.

All output has:

- `source_read_only=True`
- `execution_allowed=False`

## Files

- `red_bar_lab/services/historical_attribution_audit.py`
- replacement `red_bar_lab/ui/pages/shadow_directional_diagnostics.py`
- `red_bar_lab/tests/test_historical_attribution_audit.py`

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_historical_attribution_audit.py `
  red_bar_lab/tests/test_signal_trade_attribution.py `
  red_bar_lab/tests/test_existing_pipeline_attribution_hooks.py -q
```

## Next

Sprint 4.3.5.2 will reconstruct the complete historical chain per matched
pipeline signal and produce preview outcomes without persistence.
