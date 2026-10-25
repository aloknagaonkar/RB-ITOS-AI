# Confirmed strategy -> controlled simulator -> ownership audit

Production execution stays disabled. This package changes the existing SIMULATOR
foundation and adds an opt-in confirmed-event bridge. It never imports Upstox
transport or account pin credentials. It changes no strategy rules, live Hilega
worker, Sandbox execution worker, broker observer, account adapter or frontend.

## Important distinctions

- The default demonstration is fully isolated in a NEW output directory.
- Optional journal mode reads the hash-chained live strategy decision journal,
  but executes only through the existing SimBroker and simulator control DB.
- Synthetic contracts are SIMULATOR|CE and SIMULATOR|PE. Default quantity 65 and
  price 100 are test parameters, NOT current exchange lot/instrument/quote data.
- NIFTY signal prices are NEVER substituted for option premiums. No results in
  this package measure strategy profit or actual Upstox execution quality.
- Broker account pins, real positions and real fills are not used. Generated
  simulated executions have SIMULATOR_GENERATED provenance. The ownership ledger
  consumes these synthetic fixtures, never relabelled real broker evidence.
- The existing UI can display simulator orders/positions and lifecycle events
  from the same DB. It still does not control real Upstox or the original
  strategy/Sandbox worker. Production readiness remains NOT_CLEARED.

## Implemented behavior

1. Only PROCESSED DIRECTIONAL_DECISION / DIRECTIONAL_SESSION_CUTOFF records with
   exact deployed policy/version are eligible. Recovered/reconstructed history,
   setup/candidate/armed information and canonical setup events cannot buy.
2. Confirmed event details and entry times must agree with a completed 5m
   boundary. Stable execution IDs ignore delivery hash changes. Conflicting
   event definitions pause the simulator rather than place another entry.
3. Entries call the same central Service.submit_entry gate used by the control
   foundation. Pause, control version, next-fresh-signal restriction, 60-second
   signal freshness, reconciliation and existing exposure checks remain active.
4. A strategy exit can close while PAUSED but never arms/resumes. It is separate
   from manual Exit, which still pauses as agreed. Exit references must match the
   original confirmed entry. Old exit events cannot close a newer trade.
5. Exit first, then opposite entry. Pending/partial SELL blocks reversal BUY.
   Pause or any control version change cancels the waiting BUY. Waiting cannot
   bypass freshness: after 60 seconds that entry is blocked, not restored later.
6. Each planned bridge submission is persisted before the central submission
   gate. Restart finds an existing durable intent without placing a duplicate.
   An interrupted plan without a durable intent requires review; no blind retry.
7. Simulator executions now have individual persistent trade IDs, quantity,
   price and timestamp. Auto-filled fake SELLs and explicit fill injections write
   those records atomically with the simulated order update. Existing cumulative
   fill injection price means cumulative average; increments are derived at the
   simulator generation point, never inferred by the ownership reader. Synthetic
   arithmetic may have Decimal rounding and is not an exchange-price model.
8. Missing historical simulator executions are NOT backfilled from order status.
   Legacy evidence gaps require review. Existing normal/manual exit controls and
   actual strategy rules retain their behavior, covered by regression tests.
9. Ownership links source event -> simulator intent -> SIM order -> individual
   simulated fills. Parent-linked simulator manual exits are included. Unknown
   external simulated activity is blocked; it is not adopted from a symbol match.
10. Bridge and control locks serialize submissions. Browser refresh is not used
    for pause/resume enforcement or fill processing. Source truncation, replacement,
    incomplete final line, bad hash or wrong new policy version stops processing.

Real production ownership, real option quote/contract mapping, allocation/risk
reservation, external broker exits and real SELL-before-BUY reconciliation remain
pending. This module is not a real broker execution adapter.

## Stage and validate on your VM

Keep Upstox Production PAUSED. Extract into ~/RB-ITOS-AI:

```bash
cd ~/RB-ITOS-AI
set +e
unzip -n hilega-production-simulator-bridge.zip
.venv/bin/python hilega-production-simulator-bridge/install.py \
  --stage data/research/hilega-simulator-bridge-stage
.venv/bin/python hilega-production-simulator-bridge/validate.py \
  --stage data/research/hilega-simulator-bridge-stage \
  --output data/research/hilega-simulator-bridge-validation.json
```

Validation runs new bridge/fill-journal/API-control integration tests, previous
production/identity/ownership tests, strategy/dispatch regression tests and a
synthetic lifecycle demonstration. It starts no services, makes no broker
requests and changes no active app DB. Observation is disabled in test processes.
No tests, demo, replay or build were run in the preparation environment; only
Python syntax was checked. No frontend changes, so no frontend build is needed.

## Apply only after PASS

```bash
.venv/bin/python hilega-production-simulator-bridge/install.py --apply \
  --validation data/research/hilega-simulator-bridge-validation.json
```

Installer requires the exact previously validated simulator foundation and
ownership ledger. It backs up the foundation file and records new files for
rollback. Do not bypass differing-source guards. Do not restore older trading
SQLite databases as a rollback; stop the bridge and restore source appropriately.

After APPLIED, restart ONLY UI/API to load the simulator foundation update:

```bash
bash scripts/restart_hilega_ui_api_safe.sh
```

That preserves the strategy worker and re-pauses the simulation workspace. It
DOES NOT start the bridge or enable trading. No new environment flag is needed
for the isolated demo:

```bash
PYTHONPATH=backend:. .venv/bin/python scripts/hilega_production_simulator_bridge.py \
  --demo --output data/research/hilega-simulator-bridge-demo-v1
```

Use a new demo directory each time. Outputs summary.md, report.json, simulator DB
and separate ownership-fixture DB. Summary covers armed/no-order, confirmed entry,
pending reversal SELL, pause blocking opposite BUY, next fresh entry, completed
reversal and manual exit. Prices/fills are synthetic; no performance claims.

## Optional live-journal SIMULATION reader — do not enable before validation

This development integration is OFF by default, is not started by restart.sh and
has no production order permission. It uses the existing simulator DB, so its
orders are visible in the existing Production workspace's SIM sections. Do not
point its DB or source paths to a real execution ledger. Keep real accounts out
of this simulation. Worker heartbeat/alert integration is still pending; an
ARMED simulator label alone does not prove this optional process is running.

Only after the demo/validation pass and an operator explicitly elects to test it:
set HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED=1 in .env while keeping
HILEGA_PRODUCTION_WORKSPACE_MODE=SIMULATION_ONLY. Then run from an SSH terminal:

```bash
PYTHONPATH=backend:. .venv/bin/python scripts/hilega_production_simulator_bridge.py --watch
```

Startup durably PAUSES simulator entries. First use baselines the existing audit
journal; it does not replay old entries. After startup the operator can Resume
through the existing UI/CLI for the NEXT FRESH confirmed signal. Default journal:
data/live-observation/hilega-directional-v1/step-audit.jsonl. Source cursor and
bridge idempotency are persistent. A 5-second local polling loop needs no browser.

By default fake BUYs remain pending until a simulator fill injection or exit
cancels them. --synthetic-fills explicitly auto-fills fake BUYs at configured
price 100; fake SELLs use the existing simulator's auto-fill behavior. Neither
option uses a real quote, real lot or real order. Do not interpret these fills
as research backtest fills or broker P&L. No production activation flag exists.

Normal process exit/exception re-pauses. A forced kill cannot run cleanup; before
resuming, inspect the process, simulator orders and reconciliation. Restart
pauses again; there is no automatic resume. Do not enable the reader unattended
before heartbeat/recovery monitoring is implemented and validated.

No changes are needed to the real Hilega decision audit: the bridge consumes its
confirmed output. Bridge lifecycle events appear only in the simulator/production
preparation audit, alongside separate synthetic ownership reports. The live
strategy itself keeps generating and auditing signals while trading is paused.
