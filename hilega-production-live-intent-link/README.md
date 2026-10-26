# Durable live intent evidence link — read-only staged assessment

This standalone package inspects existing local records and records a separate
assessment. No installer/apply, application changes, API/worker restart, network
calls, token reads, order placement/cancellation, ledger fill updates, reservation
release, Resume or production enablement. The existing production gate is untouched.

## Scope and honest interpretation

This stage adds a durable audit projection of a locally consistent BUY chain:
controller intent + existing held reservation -> fingerprinted adapter request ->
committed PLACE attempt -> stored local HTTP receipt -> exact broker order ID ->
fresh signed account capture and its explicit fills. It never adopts an order by
symbol, quantity, tag or a manually supplied broker order ID. There is no receipt
import, missing-receipt recovery, instrument remapping or SELL attribution API.

Existing `sim_allocation_reservations` records prove only that a local hold exists;
they do NOT prove real cash allocation. Existing SIMULATOR|CE/PE intent instruments
will fail exact instrument checks. The output never claims strategy ownership,
broker-attested transport provenance, true flatness or release permission.

The source transport receipts are local unsigned SQLite records. A locally signed
account capture authenticates the capture under the user's local pin; it does not
independently authenticate the historical intent/receipt or prove strategy ownership.
This package is a structural chain assessor, NOT the final production ownership
binding implementation. Its normal success is deliberately named
`LOCAL_CHAIN_CONSISTENT_AUTHORITY_NOT_GRANTED`.

Because real mutations are closed in the supplied adapter, there may be NO genuine
live attempts/receipts available. Empty-account captures, synthetic fixtures or a
passing test cannot fill that evidence gap. Do not manufacture receipts, edit mode,
change scope, alter instrument mappings, loosen dependency hashes or open the gate
to obtain a success. Missing evidence must remain BLOCKED. Existing consolidated
fixtures use an explicit offline scope and cannot be passed to this live assessor.

## Ubuntu VM: validate first

Extract this ZIP in `~/RB-ITOS-AI`; it adds only the new directory
`hilega-production-live-intent-link/`. Do not run an installer or restart anything.

```bash
cd ~/RB-ITOS-AI
set +e
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-production-live-intent-link/test_link.py \
  hilega-production-live-evidence-review/test_review.py
```

Share the test summary and any failure. Tests have NOT been run by the author.
Only AST syntax parsing and static inspection were performed. All test intent,
receipt and capture data are synthetic, including test receipts labelled HTTP;
they are never exported into the application or offered as live proof.

Coverage includes no-fill acknowledgement, explicit partial/full fills, missing
intent/attempt/receipt, unknown/split acknowledgement, manual order-ID substitution,
fixture/cross-account rejection, stale/tampered captures, latest failed review,
source database byte preservation, restart, binding conflict, output separation,
session isolation and missing-position-without-SELL rejection.

## Optional real-record assessment — after VM tests

Use only confirmed real source paths; no real adapter DB path was established by
the uploaded code. The current workspace defaults to
`data/research/hilega-production-workspace/sim.sqlite`, which is a simulator store,
NOT proof of a real strategy intent. Do not substitute offline demo databases.

The following is a command template, not a command to run with literal placeholders:

```bash
PYTHONPATH=backend:. .venv/bin/python -u \
  hilega-production-live-intent-link/run.py \
  --controller-db /confirmed/path/to/controller.sqlite \
  --adapter-db /confirmed/path/to/live-adapter.sqlite \
  --review-dir /confirmed/path/to/current-session-live-evidence-review \
  --output data/research/hilega-live-intent-link-YYYYMMDD
```

The pin defaults to `~/hilega-private/upstox-account-pin.json`. No token is needed.
The latest capture must be at most 30 seconds old and have a successful current
review. The command does not refresh it. An old Oct 26 capture cannot be replayed
as current evidence on another session. Do not change clocks or freshness limits.

Sources are opened SQLite read-only with query_only enabled. The tool revalidates
all stored capture signatures, digests and account continuity; checks the latest
review state; then checks latest-capture freshness. Each source DB has its own read
transaction; no cross-database/remote atomicity is claimed. Trusted, access-controlled
local paths are required. The output must be a separate dedicated directory, never
the source DB directory or an ancestor containing sources or the private pin.

Private IDs and evidence fingerprints remain in owner-only `assessment.sqlite3`.
Stdout contains counts and status flags only. Share stdout/test summaries, never
raw captures, database contents, the pin or credentials. Conflicting durable
request/order bindings are blocked without overwriting the previous binding.
Every run revalidates current evidence; stored bindings are historical audit only.
A failure is recorded as the latest assessment, never hidden by earlier success.
Output is isolated per account/session.

Exit 0: local chain is consistent; ALL execution/ownership/release permissions false.
Exit 2: missing/invalid evidence or access/storage error. No permission to trade.

## Remaining production gates

- Proven real controller/transport binding with authoritative controls and real
  instrument/contract mapping; independently reviewed provenance and recovery.
- Actual broker fill/position reconciliation and scoped strategy ownership.
- Real partial-entry cancel/cleanup and direct Upstox partial/full exit attribution.
- Fresh terminal-flat ownership proof before exactly-once real reservation release.
- Actual cash debit/reflection/fees/buffer and 50% reservation integration.
- Fresh market-hours contract/quote/P&L checks; daily-loss enforcement.
- Production readiness, alerts/escalation, restart/backup/rollback validation.
- Separately authorized supervised pilot after all required gates pass.

The 400-test offline lifecycle milestone and earlier 25-test live continuity review
remain reported VM results; this new package does not reclassify them as live proof.
