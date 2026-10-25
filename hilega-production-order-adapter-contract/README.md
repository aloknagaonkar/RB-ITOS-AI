# Offline order-adapter contract and fake transport faults

NO installation/apply, tokens, network imports, real account/broker/simulator DB
access, strategy edits or production activation. This standalone contract is NOT
an Upstox HTTP adapter and does not alter installed execution paths. It accepts
only the exact bundled FakeTransport, which persists synthetic orders/executions
in a NEW isolated SQLite DB. No actual broker request can be made by this package.

VM tests first; only Python AST syntax was checked in preparation. No tests,
demonstration or frontend build ran locally.

cd ~/RB-ITOS-AI
set +e
unzip -n hilega-production-order-adapter-contract.zip
.venv/bin/python -m pytest -q hilega-production-order-adapter-contract/test_adapter.py

After tests pass:
.venv/bin/python -u hilega-production-order-adapter-contract/demo.py \
 --output data/research/hilega-order-adapter-contract-demo-v1

## Contract checks
- Intent IN_FLIGHT is durably committed before fake place call. Post-acceptance
  response loss becomes UNKNOWN and pauses entries. A crash before acknowledgement
  leaves durable IN_FLIGHT; reconciliation is mandatory before any new BUY.
- Same request ID/plan returns existing intent, never another POST, including
  unknown/rejected/completed requests. Changed plan under the same ID is rejected.
- Empty/missing order result is NOT rejection. It remains unresolved; never retry
  blindly. Explicit synthetic REJECTED evidence is terminal and different.
- Unknown order binding uses explicit unique fake client_reference plus exact
  account, instrument, product, side and quantity. This is a trusted OFFLINE
  reference, NOT an Upstox server idempotency key or permission to match real
  orders by tag. Real tag/broker lookup limitations remain pending.
- Coherent complete fake snapshots enforce scope, age<=30s, monotonically
  increasing generation, same-generation content stability and immutable execution
  IDs. No missing/corrected executions, regressing fills, identity mismatches or
  unmapped account orders are adopted. Fake generation is NOT an Upstox field.
- All orders/fills/positions must reconcile before updates are committed together.
  Short/negative positions and SELL fills beyond owned entry are rejected.
- Pending-entry Pause cleanup cancels, discovers partial/full fills and closes
  discovered quantity. Already-reconciled established fills are retained on Pause.
  Manual exit pauses. Strategy exit can preserve control mode.
- Exit quantity comes from reconciled entry minus verified exits. Pending SELL
  blocks opposite BUY. A terminal partially filled exit with remaining exposure
  requires review, not automatic second SELL or oversell. Repeated exit request
  cannot create another SELL. Cancellation response loss requires reconciliation.
- Adapter restart always pauses; exact fake transport and durable state are reused.
- A single host file lock serializes controls and submission. Transport call stays
  inside lock. Later real HTTP transport must have bounded timeouts; this package
  does not establish real network latency behaviour or API stop latency guarantees.

## Boundaries still pending
This is a contract model with its own fake state store, not central simulator
integration or production order transport. It does NOT wire actual UI/CLI, cash
reservations, health, quote/contract checks, session rollover, daily loss or source
journal into this adapter. Prior protections must be retained at eventual shared
submission boundary, not replaced by this standalone model.

No real broker fill ownership, automatic external exit attribution, transport
schema mapping, account pin authentication, static IP validation or actual Upstox
submission/cancellation is implemented here. Fake snapshots assume complete
per-order fill evidence and a generation unavailable in sequential live API reads.
A real adapter needs verified snapshot/stream ordering and correlation without
inventing generation or relabelling non-atomic reads coherent.

Request IDs are local contract IDs, not an assertion that provider POST retries
are safe. Trade ID scope is global in the fake venue; real provider execution
identity scope must be mapped correctly later. No unknown intent can be deleted
or reset to make new entries succeed.

Single instrument/position at a time. Prices100/quantity65 are explicit fixture
values, not current contracts or exchange metadata. No charges/slippage/P&L or
cash-budget enforcement in this model; all output permissions remain false.

Outputs: private directory, fake-contract.sqlite, report.json, summary.md. No real
balances/account IDs/tokens. No market session or actual trade is required.
A PASS proves the supplied fake scenarios, not production readiness.
