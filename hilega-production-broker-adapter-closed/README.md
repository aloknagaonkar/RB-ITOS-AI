# Broker adapter with production gate closed in code

Standalone implementation, not an application promotion. No apply/install/restart.

## Delivered

- Fixed-host V3 place/cancel HTTP transport code behind require_live_clearance(),
  which always raises before token access, Request creation or network activity.
  No environment/config flag can open this gate. Redirects are refused, bounded
  responses and timeouts are handled, and automatic retries are absent.
- Durable immutable request and reservation REFERENCE (not a verified funds hold).
- One attempt per request/operation, committed before transport. Repeated submit
  or cancel returns the original attempt, never another transport call.
- Context-bound response receipts committed before order-ID binding. Normal
  recovery replays stored receipts, then invalidates cached fill state.
- Lost response before receipt persistence remains UNKNOWN; no automatic order
  adoption by tag/instrument/client reference, and no caller acknowledgement API.
- Cancel acknowledgement is separate from order/fill reconciliation. Partial
  filled quantity is never treated as flat or used to release funds.
- Verified read-only account capture handling for known bound IDs; new/unowned
  activity requires ownership review. Real ownership remains unverified.

This module does NOT reserve/release cash, calculate P&L, validate current quotes,
control Pause/Resume, manage partial-exit SELL sizing or make live-readiness decisions.
Those authorities remain in the execution controller and ownership/risk layers.
There is no live attempt in this package while the gate is closed, even if a token
exists. HTTP mutation code is unexecuted and not broker-validated. Opening the gate
would require a separate reviewed change and integration, not changing a setting.

## VM validation

```bash
cd ~/RB-ITOS-AI
set +e
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-production-broker-adapter-closed/test_adapter.py

PYTHONPATH=backend:. .venv/bin/python -u \
  hilega-production-broker-adapter-closed/demo.py \
  --output data/research/hilega-broker-adapter-closed-demo-v1
result=$?
echo "Demo exit code: $result"
```

After tests/demo pass, optional real account GET-only baseline:

```bash
PYTHONPATH=backend:. .venv/bin/python \
  hilega-production-broker-adapter-closed/read.py \
  --env-file .env \
  --output data/research/hilega-broker-adapter-closed-read-v1
result=$?
echo "Read-only exit code: $result"
```

It uses the existing private account pin and validated GET-only collector, and a
separate LIVE_CLOSED database. No request is prepared/submitted by read.py.
Do not reuse offline fixture DBs as live stores. Output directories must be new.
No raw profile/account IDs or tokens are printed. Schema/source mismatches block.

## Tests and limitations

Tests use an exact local FixtureTransport with explicit injected responses. They
cover durable attempts/receipts, lost responses, split acknowledgement rejection,
restart boundaries, partial fixture status/cancel, repeated/concurrent requests,
read-only signatures/scope and the closed gate before any token/network call.
Fixture fill status is not a full execution ledger, trade attribution or P&L.
No actual HTTP mutation or broker-side error/timeout behavior is validated.
Authoring verification was AST parsing only; run tests/demo on the VM.

The transport is not yet connected to the installed application, its authenticated
UI/CLI, reservations, ownership ledger, health gates or risk controls. The existing
SIMULATION_ONLY runtime stays unchanged. See REMAINING.md for promotion prerequisites.
