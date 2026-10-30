# Atomic exit binding stage v1

Development stage only. This does not deploy application code or enable exits.

## Validate on the VM
    .venv/bin/python -m zipfile -e hilega-atomic-exit-binding-stage-v1.zip hilega-atomic-exit-binding-stage-tools-v1
    .venv/bin/python -W error::ResourceWarning -m unittest discover -s hilega-atomic-exit-binding-stage-tools-v1 -p 'test_*.py' -v
    .venv/bin/python -W error::ResourceWarning hilega-atomic-exit-binding-stage-tools-v1/validate_atomic_fixture.py

Expected: 115 tests and ATOMIC_EXIT_BINDING_FIXTURE_PASS.
No live account reads, .env/pin access, production database writes, service changes
or order submissions occur in these commands. Temporary fixture databases are
removed. Extract into a fresh directory.

## Atomic operation
bind_fixture_exit atomically writes a staged exit reference, a disabled SELL
adapter request, their binding fingerprints and a fixture audit event.
It uses an attached SQLite transaction on distinct existing same-filesystem
DELETE-journal databases with FULL synchronous and BEGIN IMMEDIATE.

The exit reference is validated for local signature, fingerprints, session and
fresh creation (10 seconds at the supplied fixture as_of). The actual supplied
adapter validated_request function is reused verbatim through adapter_reference.
Parent request/order references and instrument/product/direction must agree.
Reference-only store metadata and fixture adapter scope must agree.
The SQL transaction rechecks the parent row before committing.

Same-key replay does not duplicate requests. Changed draft or intent conflicts.
A different pending exit for the same parent is rejected. Existing separately
recorded references cannot silently be adopted into an atomic transaction.
Any failed insert/checkpoint rolls both databases back. Tests inject failures
after the reference, after the request and before commit.

No exit attempt, receipt or broker order is manufactured. No transport is called.
Existing parent entry attempts/receipts in fixtures are left unchanged.

## Explicit limits
The new binding writer only accepts FIXTURE: account scope and OFFLINE_FIXTURE
adapter metadata. It refuses UPSTOX/live scope and LIVE_CLOSED adapters.
This must NOT be made live by deleting these guards or relabelling live evidence.
The running application's schema and route are not changed.

This stage uses a separate staged reference ledger, not the running application
preparation tables. It is not yet the atomic production application/adapter
integration. Rollback tests establish software transaction behavior, not
power-failure certification. Freshness uses an explicit fixture clock; a live
integration will need clock and evidence checks again after database waits.

The stage carries forward the previous read-only reference/signature checks and
exit-intent fixtures. Those remain references, not strategy ownership authority.
No daily-loss or entry-cost limit has been chosen. Fees, P&L, real reservation,
exit acknowledgements, chronological SELL fill attribution, terminal flatness,
unknown-outcome recovery and release authority remain pending.

## Validation
115 local tests passed with ResourceWarning treated as an error.
The first 100 tests cover the previous components; 15 cover atomic exit binding.
VM validation pending. Live runtime unchanged. No go-live clearance.
