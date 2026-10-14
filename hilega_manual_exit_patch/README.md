# Hilega manual exit and recovery — Sandbox v1

Prepared against the recovered RB-ITOS-AI snapshot. Additive installer preserves deployed strategy rules and other patches when its unique anchors match. This is not installed on your VM yet. Live order execution stays disabled; no live adapter is supplied.

## User flow

After a Sandbox BUY, click **Exit all Sandbox positions** in the Sandbox dashboard. The API queues a persistent request; the existing basket worker closes the strategy-owned legs. New entries pause throughout exit and recovery. The worker checks actual order identity, filled quantities, status and average prices. Accepted SELL orders alone never release the position. After all quantities are closed, the alignment coordinator clears active ownership, canonical trade/armed state and pending candidates, keeps indicators warm, and acknowledges the reset. Automatic execution resumes for fresh qualifying signals. Continuous old alignment is consumed until it breaks; stale trade exits and old entry signals are skipped. Existing setup/confirmation intervals remain unchanged.

The main dashboard's existing P&L remains a quote-based estimate. The new manual-exit section shows confirmed filled quantities and actual fill-based P&L separately. Observation-only option snapshots are released with immutable audit evidence; exact-minute historical option exits are not fabricated.

## Automatic recovery

- Durable requests, sells and reset acknowledgements survive process restart.
- Shared basket worker lock coordinates API requests, worker submissions and reset acknowledgements.
- Duplicate clicks reuse the active request. Unknown submissions are looked up by deterministic tag, never blindly resent.
- Partial BUYs: cancel the unfilled remainder and verify terminal BUY status before selling only the filled quantity.
- Partial SELLs: await terminal status and retry only the remaining quantity; maximum three SELL attempts per leg.
- A known SELL still open after60 seconds gets one cancellation request, then status polling. A cancellation ACK alone is insufficient. If cancellation outcome remains uncertain, polling continues without a duplicate SELL.
- Transient status-reading failures are retried on subsequent worker polls. Other known legs may still be exited.
- Old automatic SELLs are reused, avoiding duplicate exits.
- Only an unchanged, captured uncertainty safety block may be cleared after reconciliation and reset. Kill switches, unrelated/new safety blocks and cutoff locks are preserved.
- Missing evidence, unsupported APIs, mismatched order identity, excessive sold quantity or exhausted attempts hold new entries and display a reconciliation reason. This is deliberate: the system cannot safely invent proof of closure.

## Provider verification is required on the VM

Current worker code tracks acknowledgements, not fills. This patch adds Sandbox-client GET /v2/order/details and DELETE /v3/order/cancel. Upstox's announcement describes Sandbox order lifecycle reads, but the currently published Sandbox-enabled API list only enumerates order mutations. GET-by-order-id and GET-by-tag support on your app/token must therefore be checked in your environment. There is no fallback to a live trading client or acknowledgement-only closure. If a status endpoint is unsupported, manual exit cannot safely submit/complete its flow and stays paused for reconciliation.

Official references:
- https://upstox.com/developer/api-documentation/get-order-details/
- https://upstox.com/developer/api-documentation/v3/cancel-order/
- https://upstox.com/developer/api-documentation/sandbox/
- https://upstox.com/developer/api-documentation/announcements/sandbox-mode-for-apis/

## Install from RB-ITOS-AI root

Extract the ZIP into the project root. It contains hilega_manual_exit_patch/install.py (not another nested archive).

Run validation and tests BEFORE installation:

```bash
source .venv/bin/activate
python hilega_manual_exit_patch/install.py --check
PYTHONPATH=backend python -m unittest discover -s hilega_manual_exit_patch/tests
```

If an anchor check fails, no project files are changed. The exact deployed version needs inspection; do not force installation.

Apply and build:

```bash
python hilega_manual_exit_patch/install.py
npm --prefix frontend run build
```

The installer prints its timestamped backup path and writes a manifest. Build failure must be resolved before restarting. Prefer installation between sessions or when flat. Restart both the observation engine and Sandbox worker to load the coordinated change:

```bash
./scripts/restart.sh
bash scripts/stop_hilega_upstox_sandbox_worker.sh
bash scripts/start_hilega_upstox_sandbox_worker.sh
bash scripts/status_hilega_upstox_sandbox_worker.sh
```

Refresh the dashboard (Ctrl+F5). The existing session arm/configuration is retained. No cron is added.

Read-only provider verification, after a Sandbox BUY exists for the current session:

```bash
PYTHONPATH=backend python -m market_lab.hilega_manual_exit_v1 --check-provider
```

Expected: ORDER_DETAILS_VERIFIED with matching quantity/status evidence. This command places no order. NO_CURRENT_SESSION_ORDER_TO_VERIFY means that it cannot yet verify the API. A rejection/404 is a provider integration blocker, not permission to treat acknowledgements as fills. Verify tag lookup as part of uncertain-submission testing before relying on that recovery path.

Read status:

```bash
PYTHONPATH=backend python -m market_lab.hilega_manual_exit_v1 --status
```

Actual manual exit is normally requested through the button. CLI equivalent (this queues real Sandbox SELLs through the worker):

```bash
PYTHONPATH=backend python -m market_lab.hilega_manual_exit_v1 --exit-all --confirm EXIT_ALL_SANDBOX_LEGS
```

Do not run that command merely as a deployment check.

## Tests and limitations

35 focused tests passed locally with injected broker transport and temporary durable journals. Coverage includes five-leg closure, partial fills, cancellation, timeouts/tag recovery, duplicate requests, restart persistence, automatic/manual collision, stale signal suppression, preserved indicators and cutoff locks, recovery-block ownership, installer guards and Sandbox-only transport endpoints. Patched Python source parses successfully. There were no broker calls and no deployment.

This environment lacks FastAPI/httpx/filelock/python-dotenv and frontend TypeScript/Vite dependencies. A full application/API integration test, frontend build and actual Sandbox order/fill acceptance test remain required on the VM. Local tests exercise the new reconciliation engine using a deterministic transport; they do not prove your provider exposes these endpoints.

Data: data/live-observation/hilega-upstox-sandbox-v2/manual-exit.json and manual-reset-acks.json. These files contain recovery evidence and must be retained with basket-events.jsonl. Do not delete them to unblock entries. After manual exits have been used, rollback requires reconciling the executed positions and source strategy state, not merely restoring code files.

## Before future live execution

Use a separate authenticated live execution adapter and execution-mode-specific command/state files. Reconcile broker orderbook, fills and strategy-owned positions before release, including exits done outside this app. Add authenticated operator roles, an audit trail, stale-data checks, bounded backoff and visible alerts for unresolved requests. Consolidate automatic and manual exits behind the same fill-aware position ledger: the existing automatic Sandbox path still uses ACK-based position accounting and is not made live-ready by this patch. Shared observation strategy reset must be isolated by execution mode before Sandbox and live run together.
