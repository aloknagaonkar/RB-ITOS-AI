# Sprint 4.3.5.1.3.4 — Timezone Normalization Fix

Install over Sprint 4.3.5.1.3.3.

## Problem

Historical sources can mix:

- timezone-naive timestamps
- timezone-aware timestamps
- UTC (`Z`) timestamps
- explicit offsets such as `+05:30`

Pandas does not allow direct comparison between tz-naive and tz-aware values.

## Fix

All timestamps used internally for audit matching are normalized to UTC-naive:

- aware → convert to UTC → remove timezone
- naive → preserve as-is

The source payload is not mutated, and original source values remain available
for display or diagnostics.

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
  red_bar_lab/tests/test_timezone_normalization_historical_audit.py `
  red_bar_lab/tests/test_signal_trade_attribution.py `
  red_bar_lab/tests/test_existing_pipeline_attribution_hooks.py -q
```
