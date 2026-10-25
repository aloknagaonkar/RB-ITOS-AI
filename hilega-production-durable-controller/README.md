# Durable offline execution controller

Standalone, offline implementation and validation. No installation/apply script.
No changes to the running application, strategy, UI, simulator bridge or Upstox.
No network imports, credentials, live transport, live enable switch or real P&L.

Unlike the earlier composition driver, reservation amounts, intents, versioned
controls, command receipts and release events live in one SQLite database. Entry
preparation is one transaction. SQLite synchronous FULL and a kernel file lock
serialize independent controller clients; broker-like fixture acceptance remains
a separate transaction so interrupted acknowledgements can be tested.

The venue is an exact local fixture, constructed internally. Its orders and fills
are synthetic. Binding by fixture reference is NOT live acknowledgement provenance.
This module is a new offline controller, not a promotion of installed application
code and not integrated with the previously validated production ownership Ledger.
Its tests do not establish live broker reconciliation or feature parity.

## Run on Ubuntu VM

```bash
cd ~/RB-ITOS-AI
set +e
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-production-durable-controller/test_controller.py
```

After tests pass:

```bash
PYTHONPATH=backend:. .venv/bin/python -u \
  hilega-production-durable-controller/demo.py \
  --output data/research/hilega-durable-controller-demo-v1
result=$?
echo "Demo exit code: $result"
```

Use a fresh output directory. Read summary.md and report.json. Authoring checks
were syntax parsing only; tests, process tests and demo must run on your VM.

## Tested scenarios (pending VM execution)

- Atomic rollback: reservation, intent and event either all commit or all roll back.
- Real child-process termination after PREPARED, IN_FLIGHT, fixture acceptance,
  and acknowledgement commits; recovery stays paused, never dispatches twice.
- Unknown acceptance with no venue evidence retains the hold and blocks recovery
  release. PREPARED can be cancelled because dispatch was never begun.
- Two real processes compete for entry: only one may reserve and submit.
- Pause request saved before waiting on the controller lock. Before dispatch it
  vetoes BUY; if acceptance already occurred, pending order cancellation/cleanup
  completes before Pause is reported complete. It cannot undo an accepted order.
- A partial fill during cancellation creates a SELL for actual filled quantity.
- Established position retained on Pause; pending exit retains hold; terminal flat
  releases once; failure inside release transaction rolls back and is recoverable.
- Stale Resume/version rejection, command-ID conflict, duplicate request suppression,
  stale cash, pre-Resume signals and pending SELL protection.

## Semantics and limitations

Initial state PAUSED. A new client object does not change controls. A worker
restart must call recover(), which pauses before reading fixture evidence.
No worker daemon/startup integration is delivered here. Unknown or prepared plans
block Resume. recover() does not automatically cancel/flatten exposure.

Pause retains established FILLED exposure. Pending-at-Pause BUY is cancelled;
any filled quantity requires a pending cleanup SELL. Manual Exit also pauses.
SELL orders remain OPEN until the fixture is explicitly filled. There is no
market execution simulation and no promise that cancellation or exit will fill.
Cancelled/partial terminal SELL with remaining exposure needs review; no automatic
replacement order is sent. No forced disposal of unrelated account positions.

Resume command replay returns its ORIGINAL receipt, not current control status.
Always read status() to display authoritative controls. The durable Pause-request
flag blocks entries even before the Pause handler acquires the submission lock.
Entry/Resume checks use server-side time/version checks, independent of browsers.

Deliberately single-session, single-instrument, fixed 65-unit fixture sizing, no
multiple-strike basket, real contract/quote checks, feed health, daily loss limit,
authentication, HTTP/API/UI/CLI service, external exit attribution or cash debit
matching. funds() accepts explicit synthetic cash and is not a broker cash feed.
Real fields and broker transport remain pending. No automatic new-session rollover.
SQLite/filesystem integrity, actual REST concurrency and live evidence mutation
must be assessed before application integration. Do not use this for trading.
