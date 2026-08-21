# Operations Centre Readiness — Implementation Progress

Branch: `feat/retire-dri-rsi-standalone`

Architectural authority: observational/read-only. No execution or legacy exit authority is changed.

## P0 implementation — complete

- [x] Strategy-owned `NEXT_RED_CANDLE` reference policy.
- [x] Reference readiness validation with deterministic reason codes.
- [x] Separate market-data, independent-strategy, Red Bar V2 and execution readiness domains.
- [x] Exact signal-ID intersections for CORE and HYBRID readiness.
- [x] Per-signal Operations readiness orchestration and UI drill-down.
- [x] Additive `signal_enrichment_outcomes` SQLite store.
- [x] READY, MISSING, FAILED, STALE and NOT_APPLICABLE persistence states.
- [x] Explicit reason codes, retry metadata, source timestamps and no-lookahead fields.
- [x] Non-blocking runtime outcome persistence with health diagnostics.
- [x] Point-in-time completed-candle result contract.
- [x] Current-session live persisted candle preference.
- [x] Explicit historical fallback and historical-session direct selection.
- [x] Future candle exclusion and no-lookahead diagnostics.
- [x] Real live persisted CSV adapter using `ArtifactLayout.live_session_path`.
- [x] Real historical repository adapter using `historical.read_day`.
- [x] Point-in-time selection wired into market-context enrichment.
- [x] Point-in-time selection wired into volume-structure enrichment.
- [x] Selected source, cutoff, latest timestamp, fallback and no-lookahead persisted per signal/stage.
- [x] Missing or failed candle selection produces explicit outcomes instead of silent skips.
- [x] Latest persisted MARKET and VOLUME diagnostics loaded per signal/stage.
- [x] Operations Centre drill-down shows source, latest candle, row count, fallback and no-lookahead.
- [x] Observed mandatory and optional field coverage for MARKET, VOLUME and OPTIONS.
- [x] Present/expected counts and percentages exposed in the drill-down.
- [x] Missing mandatory field names exposed explicitly.
- [x] Optional-field gaps remain advisory and do not block readiness.
- [x] Missing mandatory fields force the stage to MISSING.
- [x] CORE and HYBRID membership automatically exclude incomplete mandatory evidence.
- [x] Persisted READY diagnostics cannot mask current mandatory-field gaps.
- [x] Coverage diagnostics persisted with readiness outcomes.
- [x] Focused coverage, gate, view, wrapper and persistence regression tests added.

## Validation pending on Windows

- [ ] Run the focused P0 validation suite below.
- [ ] Run the complete project suite.
- [ ] Confirm current-day MARKET and VOLUME rows show `LIVE_PERSISTED` when the live CSV exists.
- [ ] Confirm fallback columns show `YES` when historical data was selected.
- [ ] Confirm no-lookahead columns show `YES` for valid point-in-time selections.
- [ ] Confirm mandatory coverage is 100% for READY stages.
- [ ] Confirm a missing mandatory field changes the stage to MISSING and removes CORE/HYBRID eligibility.
- [ ] Confirm execution remains BLOCKED and authority remains OBSERVATIONAL_ONLY.

## Focused P0 validation command

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
  red_bar_lab/tests/test_operations_center.py `
  red_bar_lab/tests/test_ui_compatibility.py
```

## Complete project validation

```powershell
python -m pytest -q red_bar_lab/tests
```

## Deferred P1 research work

These items are intentionally outside the completed P0 readiness task and remain additive research improvements:

- [ ] Separate collector freshness from per-signal alignment coverage.
- [ ] Apply liquidity eligibility before option candidate ranking.
- [ ] Remove volume double-counting from option aggregation.
- [ ] Normalize OI and volume features.
