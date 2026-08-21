# Operations Centre Readiness — Implementation Progress

Branch: `feat/retire-dri-rsi-standalone`

Architectural authority: observational/read-only. No execution or legacy exit authority is changed.

## Completed

- [x] Strategy-owned `NEXT_RED_CANDLE` reference policy.
- [x] Reference readiness validation with deterministic reason codes.
- [x] Separate market-data, independent-strategy, Red Bar V2 and execution readiness domains.
- [x] Exact signal-ID intersections for CORE and HYBRID readiness.
- [x] Per-signal Operations readiness orchestration and UI drill-down.
- [x] Additive `signal_enrichment_outcomes` SQLite store.
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
- [x] Missing or failed candle selection produces explicit enrichment outcomes instead of silent skips.
- [x] Latest persisted MARKET and VOLUME diagnostics loaded per signal/stage.
- [x] Operations Centre drill-down shows source, latest candle, row count, fallback and no-lookahead.
- [x] View-model and persisted-diagnostics regression tests added.

## Current validation state

- [x] Operations readiness and runtime persistence suites passed on Windows before this slice.
- [ ] Run the focused source-diagnostics suite below.
- [ ] Confirm current-day MARKET and VOLUME rows show `LIVE_PERSISTED` when the live CSV exists.
- [ ] Confirm fallback columns show `YES` when historical data was selected.
- [ ] Confirm no-lookahead columns show `YES` for valid point-in-time selections.

## Next P0 slice

- [ ] Replace hardcoded field-availability labels with observed field coverage.
- [ ] Calculate per-stage present/expected field counts.
- [ ] Surface missing mandatory fields and optional-field coverage separately.
- [ ] Prevent a stage from appearing READY when mandatory fields are absent.

## Later P1 work

- [ ] Separate collector freshness from per-signal alignment coverage.
- [ ] Apply liquidity eligibility before option candidate ranking.
- [ ] Remove volume double-counting from option aggregation.
- [ ] Normalize OI and volume features.

## Focused validation command

```powershell
python -m pytest -q `
  red_bar_lab/tests/test_operations_readiness_gate.py `
  red_bar_lab/tests/test_operations_readiness_view.py `
  red_bar_lab/tests/test_operations_readiness_wrapper.py `
  red_bar_lab/tests/test_operations_readiness_source_diagnostics.py `
  red_bar_lab/tests/test_signal_enrichment_outcome_store.py `
  red_bar_lab/tests/test_point_in_time_candle_source.py `
  red_bar_lab/tests/test_candle_selection_outcome.py `
  red_bar_lab/tests/test_candle_source_adapters.py
```

For the complete project suite:

```powershell
python -m pytest -q red_bar_lab/tests
```

Tests must be run in the local Windows project before this slice is considered validated.
