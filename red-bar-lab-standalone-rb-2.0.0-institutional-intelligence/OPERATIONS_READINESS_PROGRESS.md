# Operations Centre Readiness — Implementation Progress

Branch: `feat/retire-dri-rsi-standalone`

Architectural authority: observational/read-only. No execution or legacy exit authority is changed.

## Full implementation — complete

### P0 readiness

- [x] Strategy-owned `NEXT_RED_CANDLE` reference policy.
- [x] Reference readiness validation with deterministic reason codes.
- [x] Separate market-data, independent-strategy, Red Bar V2 and execution readiness domains.
- [x] Exact signal-ID intersections for CORE and HYBRID readiness.
- [x] Per-signal Operations readiness orchestration and UI drill-down.
- [x] Additive `signal_enrichment_outcomes` SQLite store.
- [x] READY, MISSING, FAILED, STALE and NOT_APPLICABLE persistence states.
- [x] Explicit reason codes, retry metadata, source timestamps and no-lookahead fields.
- [x] Non-blocking runtime outcome persistence with health diagnostics.
- [x] Point-in-time completed-candle source with live-first and historical fallback selection.
- [x] Real live persisted CSV and historical-repository adapters.
- [x] Market and volume enrichment use point-in-time candles.
- [x] Source, cutoff, latest timestamp, fallback and no-lookahead persisted per stage.
- [x] Operations Centre displays source diagnostics and per-signal blockers.
- [x] Observed mandatory and optional field coverage for MARKET, VOLUME and OPTIONS.
- [x] Missing mandatory fields force MISSING and remove CORE/HYBRID eligibility.
- [x] Coverage diagnostics persist with readiness outcomes.

### P1 additive research improvements

- [x] Collector freshness is assessed independently from per-signal alignment.
- [x] Exact per-signal alignment coverage with tolerance and no-lookahead diagnostics.
- [x] Liquidity eligibility is applied before observational option ranking.
- [x] Bid/ask spread, minimum OI and minimum volume eligibility reasons are explicit.
- [x] Option-chain aggregation deduplicates contracts before summing OI and volume.
- [x] OI, volume and OI-change features are normalized before research scoring.
- [x] Research ranking remains `OBSERVATIONAL_ONLY` and does not alter execution.
- [x] Focused regression tests added for freshness, alignment, liquidity, normalization and deduplication.

## Validation pending on Windows

- [ ] Run the focused final validation suite below.
- [ ] Run the complete project suite.
- [ ] Confirm current-day MARKET and VOLUME rows show `LIVE_PERSISTED` when available.
- [ ] Confirm historical fallback and no-lookahead diagnostics.
- [ ] Confirm mandatory coverage is 100% for READY stages.
- [ ] Confirm missing mandatory evidence removes CORE/HYBRID eligibility.
- [ ] Confirm collector freshness and signal alignment are reported independently.
- [ ] Confirm illiquid option candidates are excluded before research ranking.
- [ ] Confirm duplicated contracts are counted once in aggregate OI and volume.
- [ ] Confirm execution remains BLOCKED and authority remains OBSERVATIONAL_ONLY.

## Focused final validation

```powershell
python -m pytest -q `
  red_bar_lab/tests/test_observed_field_coverage.py `
  red_bar_lab/tests/test_operations_readiness_field_coverage.py `
  red_bar_lab/tests/test_operations_readiness_gate.py `
  red_bar_lab/tests/test_operations_readiness_view.py `
  red_bar_lab/tests/test_operations_readiness_wrapper.py `
  red_bar_lab/tests/test_operations_readiness_source_diagnostics.py `
  red_bar_lab/tests/test_operations_readiness_outcomes.py `
  red_bar_lab/tests/test_signal_enrichment_outcome_store.py `
  red_bar_lab/tests/test_point_in_time_candle_source.py `
  red_bar_lab/tests/test_candle_selection_outcome.py `
  red_bar_lab/tests/test_candle_source_adapters.py `
  red_bar_lab/tests/test_readiness_freshness_alignment.py `
  red_bar_lab/tests/test_option_research_features.py `
  red_bar_lab/tests/test_operations_center.py `
  red_bar_lab/tests/test_ui_compatibility.py
```

## Complete project validation

```powershell
python -m pytest -q red_bar_lab/tests
```

The implementation is complete. Only local Windows and Streamlit validation remain.
