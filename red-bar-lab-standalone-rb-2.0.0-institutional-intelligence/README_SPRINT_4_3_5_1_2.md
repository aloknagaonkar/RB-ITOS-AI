# Sprint 4.3.5.1.2 — Historical Audit Accuracy Hardening

Install over:

`feature/sprint-4.3.5.1-historical-attribution-audit`

after Sprint 4.3.5.1.1.

## Fixes

- canonical bundle identity:
  `instrument + detected_at + direction + primary_setup_type`;
- manual and historical backfill duplicates collapse to one bundle;
- manual rows are preferred over backfill rows;
- expanded timestamp field recognition;
- date-only source rows remain visible as
  `session_time_unavailable`;
- query-limit diagnostics;
- `result_complete=False` when a source reaches its configured cap;
- one-to-one historical assignment;
- a pipeline row cannot be reused for multiple bundles;
- ambiguous candidate matches are identified separately.

## Source diagnostics

Each source now shows:

- `raw_rows`
- `date_filtered`
- `session_filtered`
- `session_time_unavailable`
- `instrument_filtered`
- `direction_filtered`
- `matching_rows`
- `query_limit`
- `query_limit_hit`
- `result_complete`

## Safety

No candidate, opportunity, Committee, queue, paper-order or live-order write is
introduced. Execution remains blocked.

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_historical_attribution_audit.py `
  red_bar_lab/tests/test_historical_bundle_backfill_filtering.py `
  red_bar_lab/tests/test_historical_audit_accuracy_hardening.py `
  red_bar_lab/tests/test_signal_trade_attribution.py `
  red_bar_lab/tests/test_existing_pipeline_attribution_hooks.py -q
```
