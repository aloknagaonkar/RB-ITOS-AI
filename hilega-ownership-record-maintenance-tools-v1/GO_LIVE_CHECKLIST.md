# Hilega go-live checklist — 29 October 2026

Goal: confirmed fresh strategy entry -> pinned account and cash checks -> bounded BUY option allocation -> durable request/receipt/fill ownership -> controlled exit -> reconciled reservation release.

Current verdict: NOT PRODUCTION READY. This checklist is based on supplied VM outputs, not a fresh direct inspection of the VM.

## Operator policy

- Entry premium plus buffer must fit within 50% of verified available trading cash.
- No required daily maximum loss and no separate fixed rupee entry-cost limit.
- Retain the existing one-lot limit and single active local preparation.
- Unknown execution outcomes retain reservations; local reservations are not broker cash locks.

## Completed and deployed

- Entry reservation integration deployed and post-deployment verified while paused.
- Durable refused-exit recording deployed and post-deployment verified while paused.
- Closed production mutation boundary retained; no live entry/SELL submission enabled.
- Latest supplied paused-runtime verification showed matching process identities, a caught-up journal, zero execution/preparation activity and zero local cash reservations.

## Completed validation, with scope limits

- Offline application lifecycle rehearsal: 210 tests and 23 subtests passed. Entry application code handed off to separate synthetic execution; not live lifecycle integration.
- Read-only pinned account/entry ownership review: 113 tests passed on VM and a fresh signed account capture verified. Actual owned quantity remained unverified because there was no qualifying application entry, acknowledgement or fill.
- Signed ownership-record integration and closed exit context: 140 component tests plus 93 application/regression tests passed on VM. Temporary synthetic databases only; not deployed and no live ownership record persisted.
- Ownership-record maintenance package: 36 local tests passed, including directory creation, rollback and service failure behavior. VM maintenance execution remains pending.

## Pending work

1. Deploy and verify the validated ownership-record modules while paused. The supplied maintenance package installs code only; it does not enable the capture/persistence producer.
2. Connect and validate the production capture/persistence producer, including invalidation and freshness. Obtain qualifying real evidence when available; empty history cannot establish an owned quantity or zero strategy P&L.
3. Complete durable lifecycle fill/ownership reconciliation, including raw historical fill evidence, partial entries, exits/SELLs, cancellation, external activity and uncertain outcomes. The current record is a signed single-entry attestation, not a complete fill ledger.
4. Implement and validate application live SELL/exit dispatch, sizing to verified owned quantity and preserving no-resubmission behavior for unknown outcomes. The current dispatcher records refusals only.
5. Complete strategy fee attribution and net P&L evidence. Aggregate FO account/date charges and fixture gross P&L are insufficient; the provisional fee buffer is not complete live fee attribution.
6. Implement controlled reservation release only after verified terminal outcomes and reconciled exposure. Validate broker cash/debit attribution; do not infer broker cash locking from a local hold.
7. Validate a fresh eligible entry in the configured market window with sufficient verified cash, while observing all closed/preparation gates. Prior zero-cash runs did not establish funded fresh-signal admission.
8. After the above gates are validated, prepare an explicitly controlled broker pilot and final activation checks. Production trading remains disabled until then.

After-hours source staleness is compatible with the paused-safety maintenance checks. It does not establish fresh market-source admission. No daily loss limit needs to be introduced to complete this operator-approved checklist.
