# RB-ITOS-AI Hardening Release Report

## Scope

This branch hardens the observational market-evidence and paper-monitor runtime without granting live broker execution authority or changing the stable Red Bar strategy decision rules.

## Completed controls

- Source-observation evidence identity and immutable bundle persistence.
- Completed-bar timestamp and safe-evidence-time semantics.
- Required IV validation and robust median strike-step calculation.
- Explicit strike-offset precedence.
- Authoritative Trade Evidence workspace with persisted-only legacy diagnostics.
- Schema-free SQLite reads for market evidence, option participation, global readiness, futures diagnostics, and option-score history.
- Evidence schema compatibility checks and explicit schema version reporting.
- Native Upstox idempotent GET retry policy with bounded backoff, Retry-After support, and query-safe retry telemetry.
- No retry for POST or order-style operations.
- Native missing-data-preserving option-chain conversion.
- Removal of package import-time monkey patches and obsolete compatibility modules.
- Paper-monitor circuit breaker with entry suspension, bounded delay, recovery cycle, restart persistence, and position-management continuity.
- Paper-monitor safety state exposed in the Trade Evidence UI.
- Contract-quality iteration optimized without `DataFrame.iterrows()`.

## Removed compatibility modules

The following temporary modules were removed after their behavior was moved into the owning implementation:

- `red_bar_lab/services/market_evidence_quality_patch.py`
- `red_bar_lab/brokers/missing_data_option_chain.py`
- `red_bar_lab/runtime_hardening.py`

Importing `red_bar_lab` now has no runtime patching side effects.

## Supported initialization flow

Schema creation and migration remain explicit:

- `RedBarDatabase.initialize()` owns the main application schema.
- Evidence/readiness store persistence functions own their local tables and indexes.
- Read functions do not create or alter tables or indexes.

## Runtime authority

- Market Evidence remains `OBSERVATIONAL_ONLY`.
- The Authoritative Evidence tab is the sole current market conclusion.
- The legacy tab contains persisted diagnostics only.
- The paper monitor may suspend new entries but continues existing-position management and confirmed reversal exits.
- Live broker execution is not enabled by this hardening work.

## Validation commands

Focused hardening validation:

```powershell
python -m pytest -q `
  red_bar_lab/tests/test_market_evidence_quality_hardening.py `
  red_bar_lab/tests/test_market_evidence_review_hardening.py `
  red_bar_lab/tests/test_market_evidence_schema_compatibility.py `
  red_bar_lab/tests/test_option_participation_read_path.py `
  red_bar_lab/tests/test_remaining_store_read_paths.py `
  red_bar_lab/tests/test_broker_retry_observability.py `
  red_bar_lab/tests/test_remaining_hardening.py `
  red_bar_lab/tests/test_paper_monitor_circuit.py `
  red_bar_lab/tests/test_paper_monitor_circuit_persistence.py `
  red_bar_lab/tests/test_paper_monitor_circuit_integration.py `
  red_bar_lab/tests/test_market_readiness_monitor_status.py `
  red_bar_lab/tests/test_contract_quality_iteration.py
```

Full regression validation:

```powershell
python -m pytest -q red_bar_lab/tests
```

## Repository maintenance audit

The hardening audit found no remaining references to the removed compatibility modules. The package root contains project documentation and supported launch/install assets; no additional root file was deleted without a proven obsolete reference because repository cleanup must not remove operational tooling based only on filename heuristics.

## Release gate

Do not merge until the focused hardening set and complete `red_bar_lab/tests` suite pass locally. Preserve the branch for rollback until paper-monitor runtime observation is complete.
