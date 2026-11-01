# Durable closed existing-request handoff — v1

## Purpose in the trading workflow

Signal -> existing disabled preparation -> historical verification -> fresh closed review receipt -> (future authorized execution integration) -> broker BUY / fill / SELL / flat.

This package implements the durable closed review receipt, not the future execution step. It reuses the prepared request ID without preparing a second request or hold. It checks fresh signed market/cash evidence, unchanged contract, existing LIMIT price versus current ask, budget versus fresh half-cash cap, the controller version and preparation-caused PAUSED reason, no pending stop, current bridge lease/health, and absence of prior execution or closed exit records. It validates again before committing one signed receipt. Slow capture occurs outside the controller lock. A restart can replay the historical receipt without collecting again; replay grants no current clearance.

This is useful because reconnecting a restarted worker by blindly running preparation again could duplicate local reservations, while treating an old valid signature as current permission could use stale cash or an old signal. The receipt makes review durable while the request and gate remain closed.

## Run on the VM

```bash
cd ~/RB-ITOS-AI
unzip hilega-durable-closed-handoff-v1.zip
.venv/bin/python hilega-durable-closed-handoff-v1/apply_and_test.py --repo "$PWD"
```

Expected: 20 targeted tests. The runner requires the previous 12-case authenticated-handoff PASS report and pins 11 reviewed application/test files. All behavioral tests run on the VM using temporary synthetic application/adapter databases; no live account, credentials, running worker or production database is used. No installation, unit writes or service controls occur. Locally only Python syntax, expected case enumeration, payload hashes and ZIP integrity were checked; no behavioral pytest execution is claimed.

Tests cover committed Source preparation, durable replay, two rollback points, concurrent callers, four controller/stop/lease changes, control change during capture, forged evidence, fresh cash shortfall, stale time, expiry before commit, receipt tampering, UNKNOWN request refusal, closed exit refusal, a newly signed refreshed capture, ask above the original limit, and the actual installed hard order gate. One signed receipt lives in a temporary application database; attempts/receipts in the broker adapter stay empty.

## Scope and limitations

- Execution adoption remains false. This receipt is not an authorization grant, a fixture admission, or an executable outbox. The receipt uses the account evidence signing mechanism, not an independent trusted production execution authority.
- New reviews require the existing preparation-caused PAUSED state. They do not arm the controller, reconcile real broker positions, refresh the bridge themselves or alter the request price. A changed controller reason/version or expired signal blocks the review.
- The captured signed bundle passes the existing quote/cash and price-grid checks. Those pricing policy flags remain unapproved for production. Fee buffer approval and actual fee completeness are not established here.
- A historical receipt replay deliberately does not recheck current freshness and cannot be used to submit an order later. Any actual execution adopter still needs a separate current-state check and atomic claim/attempt contract.
- Application lock and attached BEGIN IMMEDIATE protect local state during the final write; the journal is checked again before commit. This does not provide atomicity with an external journal writer or the remote broker. The journal hash chain is not external authentication.
- Exactly one existing local preparation and no existing broker attempts/receipts are allowed. UNKNOWN routes to future recovery integration, never replacement or resubmission.
- Actual application exit integration, dependency/release manifest reconciliation, full combined regression, managed deployment/rollback, and production authority/policy/pilot remain pending.

Output: VM-VALIDATION.json in this package folder. Return its JSON after running. If source pins differ, stop and report the file name rather than editing the pin.
