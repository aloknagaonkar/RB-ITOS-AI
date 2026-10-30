# Staged durable exit references v1

## Scope
This is a development component, not a deployment or live exit implementation.
It records UNSENT_EXIT_REFERENCE_REQUIRES_REVIEW in a separate explicitly created
STAGED_REFERENCE_ONLY SQLite ledger. It does not write to application, adapter or
ownership databases. No executable order body, broker mutation, acknowledgement,
fill adoption, ownership grant or reservation release is implemented.

The running application remains unchanged. Production risk values remain unset.

## Validate on the VM
From the repository root, extract into a fresh directory:
    .venv/bin/python -m zipfile -e hilega-exit-intent-stage-v1.zip hilega-exit-intent-stage-tools-v1
    .venv/bin/python -W error::ResourceWarning -m unittest discover -s hilega-exit-intent-stage-tools-v1 -p 'test_*.py' -v
    .venv/bin/python -W error::ResourceWarning hilega-exit-intent-stage-tools-v1/validate_fixture.py

Expected: 100 tests pass and STAGED_EXIT_REFERENCE_FIXTURE_PASS.
The demonstration uses synthetic fixtures and temporary databases only, then
removes them. It does not read .env, the real pin, current broker/account data or
application databases. No services need restarting. Do not invoke internal store
APIs against production paths or wire them into the application yet.

## Implementation
create_reference calls the existing signed account/reference bridge. It requires:
- valid application binding and historical outer bundle signature;
- pinned signed current account capture with consistent order/trade totals;
- a current-session bound terminal parent BUY order;
- explicit matching position rows without unrelated orders or exposure;
- quantity greater than zero and no more than that parent's actual filled amount;
- a single filled order on the instrument/product; multiple entries require
  explicit allocation not supported here.

An unresolved parent, missing position, nonterminal entry, unlinked activity or
unknown exit outcome cannot be treated as exit permission. References are
signed locally, tied to parent/request and capture fingerprints, and remain
non-executable. Full ownership, nested cash/quote revalidation and fees/P&L
remain unverified. A reference may not be supplied as a clearance credential.

ReferenceStore.create requires a fresh explicit path and never overwrites an
existing database. Store metadata binds model, scope and reference-only mode.
The ledger uses SQLite FULL synchronous and BEGIN IMMEDIATE. Parent uniqueness
prevents a second pending exit reference. The same exit key and intent payload
replays the original reference; changed quantity/reason/key payload conflicts.
A newly built reference is checked for freshness within 10 seconds at record().
A replay is historical and does not refresh the original capture or timestamp.
Reopen tests verify committed references persist. They do not certify power-loss,
disk-failure or abrupt-process-termination recovery.

No API clears the pending reference, binds an exit acknowledgement, records a
broker fill or declares flatness. Those lifecycle transitions must be designed
and validated before integration. Manual/external exits and prior-session
positions remain blocked. SELL execution is still closed in the adapter.

## Validation
100 local tests passed: the previous 85 tests plus 15 exit-reference tests.
ResourceWarning is treated as an error. Application/adapter fixture databases
remain byte-identical during staged exit recording.
VM validation pending. No live broker or runtime test occurred locally.

## Next integration work
Persist application-owned exit intent and adapter request atomically, validate
acknowledgement provenance, reconcile chronological SELL fills and remaining
quantity, handle unknown outcomes without resubmission, and verify terminal
flatness before reservation release. Production risk limits, authenticated
fees/net P&L and daily-stop enforcement are also still pending.
