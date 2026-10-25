# Durable request/acknowledgement evidence registry (mutations disabled)

No install/apply, service restart, strategy edits, active simulator DB writes,
real order submission or production activation. Reuses installed ownership and
pinned-account verifier modules. New isolated registry paths only.

Only Python AST syntax checked in preparation. No tests/demo/read-only broker
requests executed locally. VM commands:

cd ~/RB-ITOS-AI
set +e
PYTHONPATH=backend:. .venv/bin/python -m pytest -q hilega-production-intent-binding/test_registry.py

After tests pass:
PYTHONPATH=backend:. .venv/bin/python -u hilega-production-intent-binding/demo.py \
 --output data/research/hilega-intent-binding-demo-v1

Optional real account READ ONLY, after tests/demo pass:
PYTHONPATH=backend:. .venv/bin/python hilega-production-intent-binding/read.py \
 --env-file .env --output data/research/hilega-intent-binding-read-v1

Default persistent read-only registry:
data/research/hilega-disabled-live-intents/registry.sqlite
Override --registry-db only with a separate dedicated path, never the app simulator,
ownership, account pin or a production DB. Output path must be new each run; live
registry persists across runs. No existing evidence is reset. Tokens/account IDs
are not printed or saved. Raw normalized account evidence and signed snapshots
in private files are sensitive; keep outside public Git and do not upload them.

## Implemented
- Persist full disabled request draft, request fingerprint, signal timestamps,
  policy/version and opaque account scope before acknowledgement registration.
- Immutable request ID/plan conflict checks and same-session duplicate signal
  prevention. Repeat same plan recovers ownership registration idempotently.
- One DB fixed to one account scope and evidence mode, immutable on reopen.
- OFFLINE_FIXTURE mode allows explicit fixture V3 acknowledgement receipts with
  one order ID. Receipt ID/content immutable; order and intent bind one-to-one.
- Receipt persisted before separate ownership bind. Crash/retry may repeat local
  evidence binding, never an order request. A pending/incomplete link blocks proof.
- Existing tested ownership ledger validates fills, remaining quantity, freshness,
  duplicate execution evidence and exits for offline snapshots. Unmapped external
  activity remains review-required; no inferred ownership from instrument or tag.
- Child SELL draft must reference parent BUY instrument/product and quantity cap.
  This is an intent draft check, NOT proof of available exit quantity. Actual
  quantity proof comes later from ownership reconciliation; no SELL is sent.
- Registry restart retains drafts, receipts and ownership evidence. Freshness can
  expire without erasing historical executions. Duplicate snapshots idempotent.
- LIVE_READ_ONLY mode verifies signed captured account evidence with existing
  private account pin and stores the immutable snapshot. Empty account baseline is
  not ownership proof; real orders/exposure become UNMAPPED_REAL_ACTIVITY_REVIEW.

## Explicit safety boundary
bind_fixture_ack is REJECTED for LIVE_READ_ONLY. bind_live_ack and submit always
raise. There is no live transport receipt producer yet because real mutations
remain disabled. Importing a manually supplied order ID/response JSON cannot
create a live strategy ownership binding. Operator manual mapping is not a
substitute for trusted durable receipt provenance.

The registry lays out/persists the future live intent envelope but does not claim
to implement verified live acknowledgement provenance. That requires a real
transport inside the shared control/risk submission gate. Same-account matching
fields or an API tag alone do not prove this app originated a real order.

OFFLINE_FIXTURE and LIVE_READ_ONLY databases are never interchangeable. Pure test
fixtures use synthetic signing keys to exercise verifier failure/success paths;
these are not actual account credentials or actual live captures.

No new controls/reservation integration is deployed here. Existing simulator
Pause/health/allocation remains as installed. Production order transport, real
capital mapping, broker ownership of actual submissions, automatic external exits,
daily loss/quote risk and pilot remain pending.

## Outputs and interpretation
Offline demo: registry.sqlite and companion .ownership-fixture.sqlite, summary.md,
report.json. Explicit synthetic order/fill receipts exercise entry to exit65units.
No real cash/P&L/market session required.
Read-only run: signed account-capture.json/report.json plus persistent registry
capture row. Exit0 means signed read evidence was verified/stored, NOT ownership
or production readiness. UNMAPPED_REAL_ACTIVITY_REVIEW may require investigation
even when capture succeeds. All permissions and execution flags remain false.

The full disabled provider request mapper is copied from the previously validated
Upstox mapping milestone. It has no network mutation transport. The only actual
network path is read.py via the installed fixed-endpoint GET-only Client.

Keep actual Production workspace PAUSED, synthetic funds unconfigured, journal
reader OFF and real execution disabled. No need to place a trade for this test.
