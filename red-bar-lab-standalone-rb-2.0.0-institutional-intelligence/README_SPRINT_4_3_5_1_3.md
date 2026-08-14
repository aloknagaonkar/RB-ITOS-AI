# Sprint 4.3.5.1.3 — Targeted Pipeline Match Resolution

Install after Sprint 4.3.5.1.2 on:

`feature/sprint-4.3.5.1-historical-attribution-audit`

## Purpose

Replace broad cross-table matching with a staged exact-ID chain.

## Resolution flow

1. Find one historical `signal_attempts` row inside the v4.3 bundle window.
2. Enforce instrument and direction compatibility.
3. Select the nearest unique pipeline signal.
4. Query trade selection by exact `signal_id`.
5. Query opportunity evaluation by exact `signal_id`.
6. Query Committee evaluation by exact `signal_id`.
7. Query execution queue by exact `signal_id`.
8. Filter paper orders by exact `signal_id`.
9. Preserve the selected candidate symbol across the chain.

## Classifications

- `EXACT_CHAIN_MATCH`
- `STRONG_CHAIN_MATCH`
- `PARTIAL_CHAIN_MATCH`
- `AMBIGUOUS_MATCH`
- `NO_MATCH`

## New fields

- pipeline_signal_id/time/state
- pipeline signal candidate counts
- candidate match count
- selected candidate ID/symbol
- selection decision/reason
- opportunity count/decision/reason
- Committee count/decision/reason
- queue count/ID/status
- paper order count/ID/status
- option symbol/type
- entry/exit timestamps
- realized P&L
- chain depth
- match resolution/confidence

## Safety

This package only reads existing pipeline tables. It does not create or modify
candidates, opportunities, Committee evaluations, queue rows, paper orders, or
live orders.

## Validate

```powershell
python -m pytest `
  red_bar_lab/tests/test_historical_attribution_audit.py `
  red_bar_lab/tests/test_historical_bundle_backfill_filtering.py `
  red_bar_lab/tests/test_historical_audit_accuracy_hardening.py `
  red_bar_lab/tests/test_targeted_pipeline_match_resolution.py `
  red_bar_lab/tests/test_signal_trade_attribution.py `
  red_bar_lab/tests/test_existing_pipeline_attribution_hooks.py -q
```
