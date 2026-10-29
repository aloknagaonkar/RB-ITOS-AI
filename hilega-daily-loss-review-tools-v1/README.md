# Hilega daily-loss review v1 — offline only

This package advances the account/risk-check step while waiting for a new eligible live signal. It is standalone code, not a deployed production risk gate. It does not import the application, call a broker, read secrets, change services/configuration, arm the controller or touch a database. It must not be used to adopt an active shadow trade.

## Validate

Extract into `~/RB-ITOS-AI/hilega-daily-loss-review-tools-v1` and run the unit suite with the repository Python. Run `example_unknown_inputs.py` for a synthetic missing-input demonstration. The example does not read current broker state. Its expected result is BLOCKED.

## Review contract

`review(config, evidence, candidate, as_of=..., expected_account_scope=...)` accepts explicit caller-supplied mappings. All monetary inputs are integer paise; booleans, floats, strings, nonfinite values and invalid signs are rejected where integer amounts/counts are required. `None` is treated as unavailable, never as zero. Timestamps must be timezone-aware; scope and session must match the expected account and IST session. P&L freshness must be explicitly configured within 1–30 seconds.

The **proposed, unapproved** policy `NO_PROFIT_OFFSET_PREVIEW_V1` adds negative realized net P&L and negative open net P&L independently. Positive P&L does not offset either loss bucket or expand the budget. P&L inputs must already be net of fees, with complete fee/ownership/reconciliation evidence. These flags are caller assertions; the module does not authenticate them.

A proposed BUY CE/PE candidate supplies an approved premium-plus-fees maximum-loss cost. This is not a stop-loss estimate and does not cover SELL/futures orders. That cost is compared with both the explicit per-entry cap and the proposed remaining daily-loss budget. No production rupee limits are selected by this package. Test amounts are fictional fixtures, not recommendations or approved account limits.

A reached daily-loss limit requests a latch in its review output. An already-latched daily stop remains blocked even when the supplied P&L later recovers. **This module does not persist or reset the latch.** Durable latch storage, new-session/reset policy, restart recovery and execution-boundary enforcement remain to be implemented and validated.

Even a numerically valid assessment returns REVIEWED_ONLY, with entry_permission, production_execution_enabled, production_ready, executable_request_created, ledger writes, broker reservation, orders_sent and reservation-release permission all false. It cannot be used as a submission permit.

## Remaining integration work

- Approved policy and explicit account-specific limits; no arbitrary defaults.
- Authenticated strategy-owned realized/open net P&L and complete fee evidence.
- Reconciled position/request counts and durable loss-stop state.
- Atomic/durable entry gating alongside existing reservation and duplicate controls.
- Failure, restart and concurrent-signal tests at the execution boundary.
- Actual live submission/fill/exit/reconciliation prerequisites remain pending.

Keep the application PAUSED. This offline work does not satisfy the pending fresh-signal admission test, and does not change the already-closed transport gate.
