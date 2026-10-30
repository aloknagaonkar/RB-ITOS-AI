# Application ownership-record integration v1 — staged validation

Connects the VM-validated single-entry quantity review to signed durable application records and informational context in the closed exit dispatcher. This is a staged patch, not a live exit executor. Production submission and reservation release remain disabled.

## Run on the VM

Keep the previously validated hilega-exit-dispatch-closed-tools-v1 folder in the repository. It supplies the existing closed-dispatch regression tests. Upload this ZIP, then run:

```bash
cd ~/RB-ITOS-AI
.venv/bin/python -m zipfile -e \
  hilega-ownership-record-integration-v1.zip \
  hilega-ownership-record-integration-tools-v1

.venv/bin/python \
  hilega-ownership-record-integration-tools-v1/run_tests.py --repo "$PWD"
```

The runner checks installed baselines and package hashes, runs 140 component tests, then creates a temporary import overlay and exercises the staged runtime with existing entry/adapter/closed-dispatch regressions plus three new actual-Source scenarios. No installed code, running services or production databases are changed. It writes a public timestamped result JSON beside this README.

140 component tests passed locally. The three new actual-Source scenarios and existing VM regressions have not yet been run against this patch. Do not deploy before reviewing the VM result. No apply command or live-persistence CLI is included.

## Staged runtime behavior

The new ownership_state.record_entry_review function recomputes the read-only quantity review while holding the application SQLite write transaction and an attached read-only broker snapshot. It checks the same signed account, cash reservation, historical bundle/cash evidence, acknowledgement, fills and explicit position row as the prior review. The application must remain paused on PREPARATION_ONLY, with matching scope and no pending stop.

Three application tables are created lazily within that transaction:

- preparation_entry_ownership_state: the current signed quantity attestation or BLOCKED state.
- preparation_entry_ownership_reviews: capture fingerprints, source fingerprints and signed review records.
- preparation_entry_ownership_audit: review outcomes and audit fingerprints.

The records contain a locally signed attestation and fingerprints. Raw account captures and a complete historical fill ledger are not persisted. This is narrower than a full production ownership/fill ledger.

A failed later review commits a BLOCKED current state where safe source access is available. Wrong account scope or corrupted current state blocks the operation. Duplicate observation IDs with changed evidence are rejected/invalidate the current state. An exact replay returns the CURRENT state and never restores an older good state. Capture-time high-water checks reject older new-ID observations. A final freshness check prevents a candidate aging out during the transaction from committing. Interrupted transactions roll back together.

The modified closed exit dispatcher can attach an informational entry quantity only after verifying the record HMAC, live scope/mode, freshness, capture/assessment chronology, current local source fingerprint, direction and exact parent signal timestamp. Missing, stale, blocked, tampered or mismatched records provide no quantity context. When no ownership table exists, no private pin is read.

For the dispatcher's informational check, fixed SELECT queries read the current application transaction and a separate URI mode=ro broker snapshot. That broker snapshot stays open until after the application commit, preserving the local comparison without broker write access. Producer persistence uses a URI mode=ro broker attachment. Tests verify broker bytes remain unchanged and that broker UPDATE/DROP statements are denied.

Every exit remains REFUSED_CLOSED. Top-level exit_quantity and parent_request_id remain null; no disabled SELL or executable request is created. The context does not grant permission to sell and cannot release a reservation. After an exit/cursor/control change, a new review is needed to match the changed local source fingerprint.

## Validation scope

The component tests include restart/reopen, duplicate replay, failed-review invalidation, stale evidence, clock regression, parent/direction mismatch, source drift, transaction rollback, final freshness, broker write denial and reservation preservation, plus the earlier 113 reference/ownership tests.

The three VM scenarios use the actual installed Source through the temporary overlay. They admit a synthetic entry, use explicit FixtureTransport acknowledgements/fills in pytest temporary databases, persist the synthetic ownership review, and exercise closed exit dispatch, stale evidence and rollback. Fixture scope/mode are explicit. The test adapter mode change is guarded to pytest's temporary paths. No real account is relabelled and no broker network call is permitted in those scenarios.

## Remaining production work

A production capture/persistence producer and maintenance deployment are not activated by this package. Full lifecycle ownership, historical fill persistence, partial entry/SELL handling, order-modification history, live SELL dispatch, fee/net P&L evidence, reservation release and a controlled broker pilot remain pending.

The current account's empty history does not verify zero strategy P&L or an owned quantity. No real order is needed to validate this package. Entry allocation remains capped at 50% of verified available cash including buffer; no daily maximum loss is required.
