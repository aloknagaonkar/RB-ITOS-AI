# Durable reusable fixture journal consumer v1

## Current stage and why

The VM reported 136 passing cases for the reusable fixture cycle API. Direct API
correctness is not enough for a worker: journal redelivery or a restart between
an order result and cursor commit must not duplicate a BUY or SELL. This package
adds a separate durable fixture consumer around that unchanged API.

Flow: verified journal record -> durable progress -> preparation/BUY or linked
EXIT/SELL -> verified flat closeout -> local retirement -> durable cursor advance
-> next fresh journal entry. It does not install a running worker hook.

## Run on the VM

```bash
cd ~/RB-ITOS-AI
unzip -n hilega-reusable-journal-fixture-v1.zip
.venv/bin/python hilega-reusable-journal-fixture-v1/apply_and_test.py --repo "$PWD"
```

Expected combined cases: **152** (existing 136 plus 16 new cases). The runner
checks package hashes and semantic parity of the 33 passing baseline sources,
adds only fixture_cycle_journal.py and test_fixture_cycle_journal.py under HOME,
refuses differing target files, and executes the full VM regression. It writes
VM-VALIDATION.json. A complete PASS requires all expected cases, zero skips and
successful key reusable-cycle/journal-recovery tests.

Syntax and ZIP integrity checks here do not establish a behavioral pass. All
behavioral pytest execution is reserved for the user's VM.

## Consumer contract

- FIXTURE scope, exact OFFLINE_FIXTURE Store and hash-pinned staged adapter are
  required before opening journal/application files or calling providers.
- First use baselines the current verified journal prefix with no historical
  order replay. It requires a paused controller, no active lifecycle references,
  authenticated retired history and matching closed fake broker records.
- Signed scope/path-bound metadata, cursor and event-progress records live in
  three separate fixture_cycle_consumer_* tables. Their writes are protected by
  a separate private consumer flock, leaving Store.lock available to the API.
- Each poll handles at most one record. Non-execution records advance without
  captures. A new ENTRY requires current ARM/resume evidence from the caller's
  explicit preparation provider; the consumer does not auto-Resume controls.
- Existing committed preparation is recovered without another preparation
  capture. Durable attempts are recovered through the API without another order.
  Unknown BUY/SELL outcomes hold the cursor and retain active references.
- An acknowledged SELL holds the EXIT cursor until fresh account proof passes
  terminal-flat closeout and local reference retirement. Pending fills do not
  become flat merely because an order was acknowledged.
- After committed closeout, recovery skips the SELL path and uses fresh closure
  evidence for retirement. After committed retirement, recovery uses authenticated
  history to finish the cursor without new captures or submissions.
- Cursor advancement and completion progress commit in one local transaction.
  Prefix changes, truncation, signature changes and missing cursor state block
  processing rather than silently rebaseline.

## Validation and limits

Sixteen cases cover baseline/no replay, fourth and fifth cycles driven through
journal events with worker reconstruction, preparation/result/cursor crash gaps,
unknown BUY/SELL outcomes, closeout/retirement crash gaps, concurrent pollers,
cursor tampering, truncated journal, missing cursor, informational records,
paused entry, multi-event reversal blocking and live-scope rejection.

This initial consumer supports one confirmed execution event per record. A record
containing EXIT plus opposite ENTRY is deliberately held for explicit reversal
sequencing policy; it is not silently accepted as a live reversal implementation.
Only the reusable API's full-lot/full-entry-fill policy is supported.

Providers in tests supply synthetic signed evidence; fill updates and controller
Resume/health updates are explicit test setup. No live data freshness, broker
fill quality, production auto-Resume or unattended-worker deployment is proven.
First-use baselining intentionally skips existing records; it is not catch-up
authorization for historical signals.

No token is read and no broker order is sent. No installed runtime, production
gate, existing service or production database is modified by the installer.
Tests write temporary fixture databases and private fixture lock files. Production
execution, runtime deployment and reservation release permission remain false.

## Next step after a passing VM result

Resolve multi-event reversal and prolonged pending/partial-exit handling in the
fixture worker, then package/verify its closed runtime hook and operational
recovery. Production policy/authority decisions, actual read-only network checks,
closed deployment and an explicitly authorized funded pilot remain separate.
