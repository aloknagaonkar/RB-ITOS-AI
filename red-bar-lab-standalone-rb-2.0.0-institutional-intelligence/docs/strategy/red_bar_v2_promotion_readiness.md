# Red Bar V2 Promotion Readiness

## Purpose

Red Bar V2 promotion is evidence-driven and fail-closed. Promotion readiness does not automatically change a feature flag, open an order, alter the legacy exit engine, or authorize live trading.

## Promotion stages

### NOT_READY

At least one mandatory baseline gate has failed. Red Bar V2 must remain disabled.

### SHADOW_READY

The strategy may run in observation-only mode. No paper order may be requested or opened.

Required evidence:

- validated unit and integration baseline with zero failures;
- sufficient error-free historical replay coverage;
- sufficient legacy/worker parity comparisons with zero mismatches;
- zero duplicate-entry evidence;
- zero unresolved execution-lifecycle conflicts;
- feature flag remains disabled by default;
- legacy exit path remains unchanged.

### PAPER_READY

A named operator may separately approve a controlled paper rollout. This stage is not live-trading authorization.

Additional required evidence:

- minimum shadow-session and shadow-decision observation window;
- zero shadow runtime errors;
- candidate, context, state and parity evidence remains auditable;
- tested feature-flag rollback plan exists;
- explicit named operator approval exists.

## Default thresholds

- 76 passing Phase 1–10 tests and zero failures;
- at least 5 historical replay sessions;
- at least 10 replay candidates;
- at least 10 parity comparisons and zero mismatches;
- at least 3 shadow sessions;
- at least 20 shadow decisions;
- zero duplicate entries;
- zero unresolved lifecycle conflicts.

Thresholds may be increased for stronger validation. Lowering them requires a separate reviewed change and must not bypass fail-closed safety gates.

## Controlled rollout sequence

1. Keep both legacy execution and independent worker execution disabled.
2. Collect historical replay evidence.
3. Validate semantic parity between the legacy adapter and independent worker.
4. Enable the independent worker in shadow-only mode.
5. Collect and audit shadow decisions across the required observation window.
6. Produce a promotion-readiness report.
7. Obtain explicit named operator approval.
8. Enable controlled paper execution only through the existing feature flag and existing paper engine.
9. Keep the legacy exit engine as the sole exit authority.
10. Disable the feature flag immediately if any parity mismatch, duplicate entry, lifecycle conflict, storage/audit loss, or runtime error appears.

## Rollback

Rollback is additive and reversible:

- set Red Bar V2 execution enablement to false;
- keep or disable shadow observation independently;
- do not delete historical evidence;
- do not rewrite open or closed legacy orders;
- do not replace the existing exit engine;
- record the blocking gate and evidence reference before resuming validation.

## Explicit exclusions

Phase 11 does not:

- enable live broker trading;
- authorize automatic production promotion;
- change option selection logic;
- change stop-loss, target, trailing or exit policy;
- rewrite `automation.py` or `paper_engine.py`;
- treat a readiness report as an execution command.
