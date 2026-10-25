# Integrated offline lifecycle validation

Standalone validation only. No install/apply step, application changes, credentials,
Upstox requests, real balances, or strategy modifications. Run on the Ubuntu VM.

Uses the previously tested allocation reservation Ledger, FakeTransport order
adapter and intent Registry, plus the installed ownership reconciliation module.
Dependency SHA256 checks reject changed/missing standalone source modules.

## Commands

```bash
cd ~/RB-ITOS-AI
set +e
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-production-lifecycle-validation/test_lifecycle.py

PYTHONPATH=backend:. .venv/bin/python -u \
  hilega-production-lifecycle-validation/run.py \
  --output data/research/hilega-lifecycle-validation-v1
result=$?
echo "Validation exit code: $result"
```

Use a new output directory for each run. Output includes summary.md, report.json,
and per-scenario databases and report.json files. The runner continues after a
failed scenario, marks the overall report FAIL, and returns exit code 2.
Tests and scenarios have not been executed on the authoring workspace.

## Coverage

| Scenario | Required behavior |
|---|---|
| Interruption after reservation | Hold remains; no fake order; restart paused; no automatic retry |
| Interruption after durable intent | Hold and intent remain; no fake order; unknown outcome stays blocked |
| Accepted response lost | Pause; retain hold; reconcile the original fake order without another BUY |
| Partial entry and Pause | Cancel remaining entry; retain hold during cleanup SELL; release after verified flat |
| Established entry, restart, manual exit | Pause retains position/hold; pending exit retains hold; terminal flat releases once |
| Missing reservation | Pre-transport guard prevents fake order |
| Duplicate plan | No second reservation/order |
| Insufficient cash | No order or reservation |

## Limits and pending integration

This is a single serialized validation driver, NOT a production controller.
It deliberately composes separate databases without claiming a cross-database
atomic transaction. Orphan reservations require review and are not auto-released.
The runner uses exact offline fake order references to reconstruct a lost receipt;
this is not acceptable live receipt provenance. It cannot adopt real orders.
All acknowledgement and fill timestamps are synthetic, derived from fixture
intent times. Partial cleanup quantity is explicitly adjusted in a synthetic
request draft; real partial-exit request validation is still pending.

The fake venue adapter controls Pause/Resume in these scenarios. Installed UI
controls, running reader, strategy workers and central simulator state are not
used or changed. Production concurrency, real request provenance, authenticated
mutation transport, external broker exits, live cash accounting, market-hours
quotes, alerts and pilot approval remain separate pending work.

A PASS establishes this offline composition only. Do not enable real trading
based on this report. There is no production enable switch in this package.
