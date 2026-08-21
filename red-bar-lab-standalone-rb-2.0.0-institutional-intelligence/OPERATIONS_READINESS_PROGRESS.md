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
- [x] Active workspace wrapper for the Operations Centre.
- [x] Visible `NEXT_RED_CANDLE`, Market, Volume, Options, CORE and HYBRID stage metrics.
- [x] Visible readiness-domain table and per-signal blocker drill-down.
- [x] Focused tests for reference validation, readiness isolation, feature intersections, orchestration, view model and live database adaptation.
- [x] View-model adapter accepts both mapping fixtures and typed `ReadinessDomains` / `ReadinessDomainResult` objects.
- [x] Blocking and advisory domain reasons remain separately exposed to the renderer.
- [x] Focused Windows suite passed after the typed-domain adapter correction.
- [x] Additive `signal_enrichment_outcomes` SQLite store.
- [x] Persistable READY, MISSING, FAILED, STALE and NOT_APPLICABLE states.
- [x] Deterministic outcome IDs and idempotent attempt upserts.
- [x] Explicit reason code, retry count and final retry status fields.
- [x] Persist input source, cutoff timestamp, latest source timestamp and no-lookahead result.
- [x] Gate-to-persistence adapter for REFERENCE, MARKET, VOLUME and OPTIONS stages.
- [x] Non-blocking runtime auto-write from the Operations readiness wrapper.
- [x] Runtime persistence health exposed as READY, SKIPPED or FAILED.
- [x] Persistence failures remain diagnostic and do not block page rendering.
- [x] Explicit `persist_outcomes=False` test path for isolated UI tests.
- [x] Success-path, failure-isolation and disabled-persistence regression tests added.

## Current validation state

- [x] Earlier Operations readiness suite passed on Windows.
- [ ] Run the expanded suite with runtime persistence tests.
- [ ] Confirm `Outcome persistence: READY` appears in Streamlit.
- [ ] Confirm eight persisted rows for two confirmed signals and four stages.
- [ ] Compare exact CORE/HYBRID IDs against persisted pipeline status for the current session.

## Next P0 slice

- [ ] Add current-day completed live-candle source before historical fallback.
- [ ] Persist selected candle source, requested cutoff and latest completed timestamp.
- [ ] Enforce and persist no-lookahead selection result.
- [ ] Return explicit MISSING or FAILED outcome instead of silently skipping unavailable live candles.

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
  red_bar_lab/tests/test_operations_readiness_view.py `
  red_bar_lab/tests/test_operations_readiness_wrapper.py `
  red_bar_lab/tests/test_signal_enrichment_outcome_store.py `
  red_bar_lab/tests/test_operations_readiness_outcomes.py `
  red_bar_lab/tests/test_operations_center.py `
  red_bar_lab/tests/test_ui_compatibility.py
```

Tests must be run in the local Windows project before runtime persistence is considered validated.
