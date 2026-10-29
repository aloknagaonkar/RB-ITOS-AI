# Isolated daily-loss latch rehearsal v1

This package is standalone validation code. It does not read `.env`, connect to Upstox, import the running application, change strategy signals, resume a controller, or modify an application/adapter database. No production capital or daily-loss values are selected. All test amounts and approval flags are fictional fixture inputs.

## Validate on the VM

Extract into `~/RB-ITOS-AI/hilega-daily-loss-latch-tools-v1`. Run the bundled standard-library unittest suite (76 tests: 39 unchanged reviewer tests and 37 latch tests), then `validate_fixture.py`. The demo accepts no database argument and uses a temporary directory which is removed afterward. Expected demo result: `ISOLATED_LATCH_DEMO_PASS`.

## Implemented in the fixture

- Explicit `FIXTURE:` account scopes, a dedicated SQLite model and refusal to overwrite existing files or convert unrelated/WAL databases.
- Immutable policy per account/session and conservative loss high-water accounting. This is a high-water mark of supplied net loss buckets, not a verified gross sum of all losing trades.
- Atomic latch, state and audit writes using `BEGIN IMMEDIATE`, DELETE journal and synchronous FULL.
- Commit persistence verified by a writer subprocess exiting and a separate reader process. Concurrent reviews see serialized state. Every result still denies entry; no production entry concurrency claim is made.
- A stored stop does not clear when P&L recovers or the caller submits `daily_stop_latched=False`. Scoped externally reported stops are sticky in the fixture.
- Review request IDs are idempotent; a changed payload with the same ID is rejected. Replaying an older review reports a subsequently latched current stop and does not grant authority.
- Injected exceptions before commit roll back state and audit together, including session rollover.
- Same-session policy changes and resets are rejected. Rollover requires an explicit newer session and fresh, flat, reconciled fixture closure assertions. Old session and audit history remain.

## Limits and pending work

Inputs are caller assertions, not authenticated broker/strategy evidence. `policy_approved=True` in tests is NOT production approval. Closure assertions do not establish real reconciliation. Numeric breaches from stale/unverified P&L block review without manufacturing a verified trip. A production system still needs reliable evidence and independent fail-closed execution controls.

The fixture latch is not wired to live entry/reservation/submit transactions. Existing runtime loss limits, P&L, transport and controller state are unchanged. Persistent production enforcement, signed evidence binding, authorization, reset policy and failure recovery require a separate reviewed integration. OS power failure, disk failure and recovery from an abruptly killed in-flight writer are not certified by these tests.

`entry_permission`, `production_execution_enabled`, `orders_sent` and `production_ready` remain false. A durable latch reported by this package belongs only to its isolated fixture database. Do not copy fixture rows, scopes, approval flags or reconciliation assertions into a live ledger. Do not remove `FIXTURE:` protection to make live inputs pass.

No services should be restarted and the application should remain PAUSED while validating this package. The historical 12:30 shadow entry is not adopted or replayed. The fresh-signal zero-cash rejection test remains pending after its earlier inconclusive bounded session.
