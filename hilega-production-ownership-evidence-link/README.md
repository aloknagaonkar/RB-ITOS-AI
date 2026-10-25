# Ownership evidence link

Isolated integration validation, not an application rollout. No installer/apply,
API/worker restart, account credentials, real orders or active ledger changes.
Reuses the installed ownership Ledger and the validated controller/adapter fixture.

## Commands

```bash
cd ~/RB-ITOS-AI
set +e
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-production-ownership-evidence-link/test_evidence.py
```

After tests pass:

```bash
PYTHONPATH=backend:. .venv/bin/python -u \
  hilega-production-ownership-evidence-link/demo.py \
  --output data/research/hilega-ownership-evidence-link-demo-v1
result=$?
echo "Demo exit code: $result"
```

Use a fresh output directory. Dependencies are hash-checked, including installed
controller/allocation/ownership and the validated adapter/link sources. Do not
change hashes to bypass a mismatch. Only Python AST parsing was done at authoring;
VM unit tests and demo remain pending.

## What it links

A prepared controller intent and held simulator reservation identify an adapter
request. Its stored PLACE attempt/receipt must match the original request hash,
mode and bound order ID. Only that known ID is bound to the ownership Ledger.
Unknown acceptance is not adopted from an order tag, symbol or account quantity.

The snapshot supplies separate explicit OFFLINE order, trade and position rows.
The fixture supplies order status and a synthetic position observation; explicit
trade rows are supplied separately. The Ledger checks quantities, identities,
timestamps, missing fills, corrections, order regressions and position consistency.
No fills are manufactured from an order's reported filled quantity.

A partial entry cancelled with 20 filled reports 20 remaining and HOLD_RETAINED.
A bound 20-unit SELL execution with matching terminal orders and flat position
allows OFFLINE_TERMINAL_FLAT_ASSESSED. Duplicate evidence does not duplicate fills.
A stale or invalidated proof cannot assess release. Unmapped activity requires review.

## Important scope boundary

Release is an ASSESSMENT ONLY. The package has no authority to release the running
controller reservation or inject broker fills into SimBroker. The isolated demo
therefore deliberately retains INR6600 even after its separate ownership fixture
assesses flat. This is expected, not a loss. Actual release requires the next
reviewed broker-port/controller reconciliation integration.

All snapshots are explicit offline evidence. LIVE_READ_ONLY snapshots are rejected,
not relabeled. This does not validate real broker fills, external exit attribution,
actual cash debit reflection or a live release path. Fixture partial-exit quantity
mapping is not an approved production partial-lot request builder. See PENDING.md.
