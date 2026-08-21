# Operations Centre Readiness — Implementation Progress

Branch: `feat/retire-dri-rsi-standalone`

Architectural authority: observational/read-only. No execution or legacy exit authority is changed.

## Completed

- [x] Strategy-owned `NEXT_RED_CANDLE` reference policy.
- [x] Reference readiness validation with deterministic reason codes.
- [x] Separate market-data, independent-strategy, Red Bar V2 and execution readiness domains.
- [x] Exact signal-ID intersections for CORE and HYBRID readiness.
- [x] Per-signal Operations readiness orchestration.
- [x] Per-signal reference, market, volume and option status drill-down contract.
- [x] UI-facing readiness view model with stable presentation fields.
- [x] Focused tests for reference validation, readiness isolation, feature intersections, orchestration and UI view model.

## In progress

- [ ] Wire the readiness view model into `ui/pages/operations_center.py`.
- [ ] Replace aggregate `min(market_ready, volume_ready)` Feature Store display.
- [ ] Add visible `NEXT_RED_CANDLE` readiness stage.
- [ ] Render readiness-domain cards and per-signal drill-down table.

## Next P0 slice

- [ ] Persist per-signal enrichment outcomes for READY, MISSING, FAILED, STALE and NOT_APPLICABLE.
- [ ] Add explicit stage reason codes and retry metadata.
- [ ] Add current-day completed live-candle source before historical fallback.
- [ ] Persist selected source, cutoff timestamp, latest candle timestamp and no-lookahead result.

## Later P1 work

- [ ] Replace hardcoded availability labels with observed field coverage.
- [ ] Separate collector freshness from per-signal alignment coverage.
- [ ] Apply liquidity eligibility before option candidate ranking.
- [ ] Remove volume double-counting from option aggregation.
- [ ] Normalize OI and volume features.

## Validation command

```powershell
python -m pytest -q `
  red_bar_lab/tests/test_red_bar_v2_reference_readiness.py `
  red_bar_lab/tests/test_readiness_domains.py `
  red_bar_lab/tests/test_feature_store_readiness.py `
  red_bar_lab/tests/test_operations_readiness_gate.py `
  red_bar_lab/tests/test_operations_readiness_view.py
```

Tests must be run in the local Windows project before the renderer integration is considered validated.
