# Exactly-once ownership release consumer — isolated offline integration

No installer/apply, active workspace access, API/worker restart, real broker request
or production enable switch. Requires marked controller-adapter fixture databases.

This extends the assessment-only step: an actual synthetic hold in the isolated
installed-controller Store is released after revalidation. A separate broker
settlement projection, audit event and release receipt commit in the SAME SQLite
transaction. SimBroker fills and original controller intent fields are not forged
or relabeled as broker executions. Control stays PAUSED and unreconciled under the
legacy simulator port; a separate broker-port promotion is still required.

## VM commands

```bash
cd ~/RB-ITOS-AI
set +e
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-production-ownership-release-consumer/test_consumer.py
```

After tests pass:

```bash
PYTHONPATH=backend:. .venv/bin/python -u \
  hilega-production-ownership-release-consumer/demo.py \
  --output data/research/hilega-ownership-release-consumer-demo-v1
result=$?
echo "Demo exit code: $result"
```

Use a fresh output directory. Only AST syntax parsing was done during authoring;
unit tests and demos must run on the VM. Dependency hashes are pinned; provide any
mismatch output instead of editing hashes to bypass it.

## Release conditions

- Exact isolated controller identity and OFFLINE adapter/account scope.
- Controller PAUSED; registered ownership entry matches controller intent/held
  reservation and adapter's reservation reference/quantity.
- Current verified snapshot ID/hash matches the stored Ledger proof.
- Every linked order has a durable PLACE attempt/receipt with matching request
  fingerprint and order ID. No manual acknowledgement adoption.
- Re-run the installed ownership Ledger validator on the complete order/trade/
  position snapshot; verify freshness, quantity identity and chronological fills.
- Target owned remaining quantity is zero and all related orders are terminal.
- Existing full hold is unreleased and matches its original amount/quantity.

The consumer holds the controller file lock and an attached-database BEGIN
IMMEDIATE transaction spanning controller, adapter, ownership and link evidence.
Rollback-journal mode is required. It validates ownership in a savepoint and rolls
back those temporary validation writes; source ownership history remains unchanged.
Database locks stay held until the controller release/settlement/receipt commit.
No distributed transaction or cross-host guarantee is claimed.

## Interruption and replay

An interruption after hold UPDATE but before receipt commit rolls back the whole
transaction. Retry revalidates fresh evidence. If the response is lost AFTER
commit, replay returns the original receipt without releasing again. A duplicate
receipt is HISTORICAL acknowledgement, not a new current-position proof; it may
be returned after the original proof expires, with current_proof_revalidated=false
and release_applied=false. New first-time release with stale proof is rejected.

Concurrent consumers release a reservation once. Conflicting request/snapshot IDs,
changed evidence, restored held funds after an existing receipt, missing receipts,
pending exit or partial filled exposure fail closed. No automatic Resume.

## Result interpretation

The terminal-flat fixture should end with held INR0.00 and one release receipt.
Partial cancellation and stale-proof fixtures deliberately retain INR6600.00.
No real cash, fills or P&L are validated. The normal running workspace is unchanged.
The synthetic released settlement is NOT imported into SimBroker; legacy Service
remains blocked for that fixture until the separate broker-port reconciliation
integration exists. Do not point the application at these fixture databases.

## Still pending

Promote a broker execution port that consumes settlement projections and fresh
verified account evidence; real receipt/fill ownership; external Upstox exits;
real cash debit/reflection; quote/contract/risk gates including daily loss limit;
production monitoring/alerts; staged regression and market-hours shadow validation;
separately approved controlled pilot. Gate stays closed throughout current work.
