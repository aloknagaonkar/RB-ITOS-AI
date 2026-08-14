# Sprint 4.3.5.1.3.2 — Selection Fallback Compatibility Fix

Install over Sprint 4.3.5.1.3.1.

## Problem

Some older historical datasets contain selection evaluations with a valid
`signal_id`, but the corresponding `signal_attempts` row is absent or outside
the readable range.

The targeted resolver previously required a signal-attempt row and therefore
returned `NO_MATCH` for all bundles.

## Fix

When no compatible signal-attempt row is found:

1. Search filtered selection rows inside the bundle window.
2. Require direction compatibility.
3. Require one unique nearest selection row.
4. Recover its `signal_id`.
5. Continue exact-ID queries for opportunity, Committee, queue and orders.
6. Mark provenance as:
   `pipeline_signal_source = SELECTION_FALLBACK`.
7. Reserve the recovered signal ID so it cannot be reused by another bundle.

Multiple equally-near selection rows remain `AMBIGUOUS_MATCH`.

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_historical_attribution_audit.py `
  red_bar_lab/tests/test_historical_bundle_backfill_filtering.py `
  red_bar_lab/tests/test_historical_audit_accuracy_hardening.py `
  red_bar_lab/tests/test_targeted_pipeline_match_resolution.py `
  red_bar_lab/tests/test_targeted_match_backward_compatibility.py `
  red_bar_lab/tests/test_selection_fallback_compatibility.py `
  red_bar_lab/tests/test_signal_trade_attribution.py `
  red_bar_lab/tests/test_existing_pipeline_attribution_hooks.py -q
```
