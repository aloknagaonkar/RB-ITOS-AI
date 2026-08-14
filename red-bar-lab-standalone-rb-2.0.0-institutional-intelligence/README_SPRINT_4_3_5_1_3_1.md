# Sprint 4.3.5.1.3.1 — Backward Compatibility Fix

Install over Sprint 4.3.5.1.3.

## Fix

Sprint 4.3.5.1.3 introduced the richer targeted-chain fields:

- `match_resolution`
- `exact_chain_matches`
- `strong_chain_matches`
- `partial_chain_matches`

Earlier Sprint 4.3.5.1 tests still expect:

- `match_method`
- `exact_matches`
- `inferred_matches`

This patch preserves both contracts.

## Legacy mapping

- `EXACT_CHAIN_MATCH` → `EXACT_SIGNAL_ID`
- `STRONG_CHAIN_MATCH` → `DIRECTION_AND_WINDOW`
- `PARTIAL_CHAIN_MATCH` → `DIRECTION_AND_WINDOW`
- `AMBIGUOUS_MATCH` → `AMBIGUOUS_MATCH`
- `NO_MATCH` → `NO_MATCH`

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_historical_attribution_audit.py `
  red_bar_lab/tests/test_historical_bundle_backfill_filtering.py `
  red_bar_lab/tests/test_historical_audit_accuracy_hardening.py `
  red_bar_lab/tests/test_targeted_pipeline_match_resolution.py `
  red_bar_lab/tests/test_targeted_match_backward_compatibility.py `
  red_bar_lab/tests/test_signal_trade_attribution.py `
  red_bar_lab/tests/test_existing_pipeline_attribution_hooks.py -q
```
