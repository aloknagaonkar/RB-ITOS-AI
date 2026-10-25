# Production preparation: read-only broker observation

This milestone adds account evidence to the existing Upstox Production workspace.
Production order submission stays disabled. Simulator controls and positions remain
separate. Existing strategy, Sandbox, signal dispatch and exit rules are untouched.

## Included

- Opt-in server-side observer, independent of browser refresh. One serialized GET
  sweep every 30 seconds after success; failures back off to 300 seconds.
- Five fixed endpoints: profile, orders, daily trade fills, positions, V3 funds.
- Explicit application User-Agent; no browser impersonation, redirects, POST,
  PUT, DELETE, order placement, modification or cancellation.
- HTTP 400/401/403/404/405 and redirects halt the observer until an operator
  corrects the issue and restarts the API. No credential changes or retries on
  access rejection. Error output contains allowlisted codes, never provider
  messages, tokens or profile details.
- Freshness uses the START of the sweep, capped at 90 seconds and same IST day.
  Missing, future, stale, corrupt and fixture snapshots are not live evidence.
- Authenticated Overview displays read-only account position rows and order/fill
  counts separately from simulator positions. Unknown exposure stays unknown.
- Cash preview uses `data.available_to_trade.cash_available_to_trade.total`
  from GET /v3/user/get-funds-and-margin with `Api-Version: 3.0`.
  Fifty percent is rounded down to paise. Pledged margin is excluded. Margin
  already used is displayed separately and NOT subtracted twice. Negative cash
  has a zero spend preview. This is not an approved allocation/reservation gate.
- Offline diagnostics detect duplicate orders/trades, fill-quantity mismatches,
  missing orders and instrument/product/side mismatches. These are observations;
  sequential snapshots can race, so inconsistencies mean REVIEW_REQUIRED.
- No false ownership claims: daily fills cannot establish overnight exposure or
  whether an external exit belongs to this strategy. No broker position or P&L
  is written into simulator state. Real P&L is not calculated here.

## Not included / production blockers

Order/fill ownership mapping, automatic external-exit attribution, broker P&L,
live quotes, configurable execution, allocation reservation, strategy-event-to-
simulator dispatch, production broker transport and real exit controls remain
pending. This package does not claim those milestones are complete.
The current PAUSED button still controls only the simulator.

Static IP and profile success do not prove stream entitlement or fills. All
readiness flags stay NOT_VALIDATED until evidence is reviewed separately.

## Stage and validate on your VM

Extract the ZIP in ~/RB-ITOS-AI. Do not overwrite active source manually.
The installer requires the exact workspace files from the prior installed
milestone, or this package's exact already-installed files. Other edits cause a
stop without replacement. It does not modify the standalone readonly collector.

```bash
cd ~/RB-ITOS-AI
set +e
.venv/bin/python hilega-production-broker-observation/install.py
.venv/bin/python hilega-production-broker-observation/install.py \
  --stage data/research/hilega-broker-observation-stage
.venv/bin/python hilega-production-broker-observation/validate.py \
  --stage data/research/hilega-broker-observation-stage \
  --output data/research/hilega-broker-observation-validation.json
```

Validation runs offline tests (with observer disabled), strategy regression
checks and frontend build on YOUR VM. No tests or frontend build were run in
the preparation environment. Validation must PASS before apply. This package
was checked for Python syntax only before delivery.

## Apply after PASS

```bash
.venv/bin/python hilega-production-broker-observation/install.py --apply \
  --validation data/research/hilega-broker-observation-validation.json
```

No services are restarted by the installer. Existing files are backed up under
backups/hilega-broker-observation-*. New files and originals are listed in
rollback.json. Reverting requires restoring originals and removing new files,
rebuilding frontend and restarting API; do not restore old simulator databases.

## One read-only snapshot after apply

```bash
PYTHONPATH=backend:. .venv/bin/python scripts/hilega_production_broker_snapshot.py \
  --env-file .env
```

Uses HILEGA_PRODUCTION_BROKER_READ_TOKEN if set, otherwise UPSTOX_ACCESS_TOKEN.
As with the previous collector, shell environment overrides dotenv values.
A dedicated read token avoids replacing existing market-data credentials.
Never paste credentials in chat. Output prints codes/checks only; monetary
amounts and account-wide rows remain in the local private snapshot (mode 600).
Default path: data/research/hilega-production-broker-observation/latest.json.
Do not commit that directory, .env or account snapshots to Git.

## Enable continuous read-only observation

Keep workspace mode SIMULATION_ONLY and controls PAUSED. Add this setting once
to .env using your local editor (do not change tokens unnecessarily):

```
HILEGA_PRODUCTION_BROKER_OBSERVE=1
```

Then rebuild and restart ONLY the UI/API using the existing safe script:

```bash
if npm --prefix frontend run build; then
  bash scripts/restart_hilega_ui_api_safe.sh
fi
```

Open Upstox Production, connect with the existing WORKSPACE CONTROL KEY (not
Upstox token), and select Overview. Wait for the first sweep. No browser refresh
is needed. The 2-second display poll is separate from the 30-second broker sweep.
The standalone snapshot command can also be used while observation is disabled;
it will not make UI evidence live until the explicit observation flag is set.

After an access error, fix the underlying token/IP issue then restart API
explicitly. Do not run the snapshot CLI repeatedly to bypass the halted monitor.
Disabling observation (.env flag 0 + safe API restart) stops collection and hides
broker evidence. An old snapshot is never proof the current account is flat.

## Manual cash validation

Compare the displayed net cash with the same account's Upstox available trading
cash. Do not compare total margin including pledge or opening balance. Record
cash, cash margin used, pledged margin and the observation time. Do not approve
production allocation until that comparison and reservation behavior are tested.

Official funds schema:
https://upstox.com/developer/api-documentation/get-funds-and-margin-v3/
