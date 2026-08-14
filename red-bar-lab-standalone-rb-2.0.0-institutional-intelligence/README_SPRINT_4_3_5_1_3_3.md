# Sprint 4.3.5.1.3.3 — Signal Schema and Unique Resolution Fix

Install over Sprint 4.3.5.1.3.2.

## Fixes

- discovers parseable timestamp fields dynamically;
- prioritizes market-event timestamps over ingestion `created_at`;
- exposes detected timestamp, signal-ID and sample field names;
- passes date-scoped raw signal/selection rows into the targeted resolver;
- groups selection evaluations by unique `signal_id`;
- multiple rows for one signal are no longer treated as ambiguity;
- ranks unique signal IDs by:
  1. exact primary signal ID,
  2. nearest event time,
  3. accepted/eligible decision,
  4. candidate rank,
  5. evaluation score;
- exposes candidate signal IDs and ambiguity reason;
- keeps one-to-one signal assignment.

## New diagnostics

Historical Source Availability now includes:

- `timestamp_fields_detected`
- `signal_id_fields_detected`
- `sample_field_names`

Targeted chain rows include:

- `pipeline_signal_time_field`
- `candidate_pipeline_signal_ids`
- `ambiguity_reason`

## Safety

Read-only research audit only. No candidate, Committee, queue, paper-order,
or live-order writes are introduced.

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_historical_attribution_audit.py `
  red_bar_lab/tests/test_historical_bundle_backfill_filtering.py `
  red_bar_lab/tests/test_historical_audit_accuracy_hardening.py `
  red_bar_lab/tests/test_targeted_pipeline_match_resolution.py `
  red_bar_lab/tests/test_targeted_match_backward_compatibility.py `
  red_bar_lab/tests/test_selection_fallback_compatibility.py `
  red_bar_lab/tests/test_signal_schema_unique_resolution.py `
  red_bar_lab/tests/test_signal_trade_attribution.py `
  red_bar_lab/tests/test_existing_pipeline_attribution_hooks.py -q
```
