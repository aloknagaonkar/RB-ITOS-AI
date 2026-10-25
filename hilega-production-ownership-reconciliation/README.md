# Ownership and reconciliation: offline foundation

Production remains disabled. This is an additive, offline evidence ledger and
fixture demonstration. It has no broker transport, no token handling and no order
submission. It does not modify current strategy, Sandbox, simulator controls,
read-only broker collection or UI. No services need restarting for this package.

## Why ownership precedes broker execution

A signal is not an order; an order acknowledgement is not a fill; a matching
instrument is not proof of strategy ownership. The new ledger links:

account scope -> signal/policy/version -> entry intent -> broker order ID ->
individual trade IDs -> remaining quantity and explicit exit intent/order/fills.

The existing broker observer strips account identity, so it cannot safely be
used as an account ownership assertion. This module deliberately rejects
LIVE_READ_ONLY, LIVE and SIMULATION_ONLY evidence. It accepts canonical
OFFLINE_FIXTURE evidence only. Real identity verification, live adapters and
strategy event dispatch remain later milestones. Current UI readiness flags
remain NOT_VALIDATED; this package does not mark them cleared.

## Included behavior

- Separate SQLite ledger, owner-only file permissions, transactional updates,
  account-scoped primary keys. Transactions serialize mapping/reconciliation.
- Deterministic entry intent identity and idempotent registration/binding.
  Conflicting signal definitions or order reassignment require review.
- Explicit policy/version/direction metadata; registering an intent does NOT
  prove strategy qualification and grants no entry permission.
- Missing order acknowledgement remains unknown; no resubmission mechanism.
- Executions come only from individual trade evidence, cross-checked against
  order identity and cumulative filled quantity. Order status cannot create fills.
- Identical trade duplicates are deduplicated; changed prices/quantities/identity,
  disappearing fills, invalid values and out-of-order evidence require review.
- Partial and cancelled-but-partially-filled orders preserve actual exposure.
- Exit fills cannot exceed confirmed entry fills or precede available entry
  quantity. Overlapping pending exits cannot reserve more than remains.
- Unmapped activity on an owned instrument and unowned account exposure block
  consistency. A missing position row is never assumed to mean zero.
- Explicit external SELL-to-entry mapping requires a recorded actor and actual
  order/fill evidence in the fixture. Instrument matching alone never attributes
  an exit. Automatic real external-exit attribution is NOT implemented.
- All evidence in a failed reconciliation rolls back atomically. Historical fill
  evidence is preserved separately from current exposure verification.
- Successful fixture evidence expires after 30 seconds; stale/failed report state
  does not present an old position quantity as current verified exposure.
- Restart preserves ownership, fills, snapshot identity and audit records.
- Reversal BUY and entry permission remain false throughout. This is not an
  execution controller; the earlier control/SimBroker tests still test controls.
- Derived realised premium value uses weighted average entry price and sell fill
  values. It is synthetic gross currency arithmetic, not NIFTY points, net broker
  P&L or a live price. Fees and unrealised P&L are not calculated.
- Generic fixture quantities are not proof of exchange lot-size compliance.

## Stage and validate on your VM

Download/extract the ZIP in ~/RB-ITOS-AI. Do not manually copy files into backend.

```bash
cd ~/RB-ITOS-AI
set +e
unzip -n hilega-production-ownership-reconciliation.zip
.venv/bin/python hilega-production-ownership-reconciliation/install.py \
  --stage data/research/hilega-ownership-stage
.venv/bin/python hilega-production-ownership-reconciliation/validate.py \
  --stage data/research/hilega-ownership-stage \
  --output data/research/hilega-ownership-validation.json
```

Validation runs the new ownership tests, existing production control/workspace/
broker-observation tests and current strategy/dispatch regression tests, followed
by the synthetic lifecycle CLI in an isolated temporary directory. Broker
observation is disabled during validation. No project tests, replay, demo or
frontend build were run in the preparation environment. Python syntax only was
checked before delivery. There are no frontend changes, so no build is required.

## Apply after PASS

```bash
.venv/bin/python hilega-production-ownership-reconciliation/install.py --apply \
  --validation data/research/hilega-ownership-validation.json
```

The installer validates package hashes and VM validation report. All three source
files are new; if a different file already exists at any target, installation
stops without replacement. It records backups/rollback metadata. Existing active
files and strategy files are not changed.

After APPLIED, print the synthetic lifecycle and save its audit details:

```bash
PYTHONPATH=backend:. .venv/bin/python scripts/hilega_production_ownership_demo.py \
  --output data/research/hilega-ownership-demo-v1
```

Use a fresh output directory for every invocation. The demo refuses an existing
output directory, so it cannot overwrite existing evidence or use a real ledger.

Outputs:
- summary.md: phase, result/reason, verified remaining quantity, synthetic gross
  realised premium value. Unknown/stale exposure is explicitly unknown.
- report.json: signal intents, order bindings, individual historical fills,
  reconciliation results and sequenced lifecycle events.
- ownership-fixture.sqlite: isolated synthetic ledger, not the simulator DB.

Expected lifecycle: unknown acceptance blocks -> 20-unit partial entry -> unmapped
external SELL blocks -> explicit synthetic mapping leaves 10 -> remainder closes
with execution evidence -> duplicate snapshot doesn't duplicate fills -> stale
snapshot hides current quantity. These are synthetic fixtures, not a replay of
an actual market date or a validation of Upstox fills.

Keep Upstox Production PAUSED. Real broker execution remains disabled. No new
.env settings, access keys, browser refresh or API restart are required here.

## Pending before live wiring

1. Verify broker account identity and bind it to a persistent account scope.
2. Adapt fresh broker order/trade/position data into a validated canonical model.
3. Feed confirmed strategy events through the existing pause/version/idempotency
   controls into simulated orders; register actual resulting intent/order links.
4. Verify external activity attribution with explicit ownership and fill evidence.
5. Integrate read-only ownership status into UI without conflating simulator state.
6. Implement reservation, contract/quote checks, token/feed health and loss limits.
7. Only after those validations: separately approved production transport/pilot.
