# Staged controller-to-adapter preparation

Standalone integration stage for the current production checklist. Adds only this
new directory; no installer/apply, source replacement, active workspace DB access,
API/worker restart, browser changes or production enable switch.

## What this stage implements

- Reuses the installed Store and Service controls, control file lock, stop generation,
  reconciliation-freshness logic and bridge health/lease checks in an isolated DB.
- Accepts an exact NSE_FO|numeric broker-format key and validates supplied Nifty
  option metadata/direction/expiry/lot/freeze rules through the existing mapping.
  No SIMULATOR|CE/PE conversion or guessed fallback instrument.
- Prepares one lot of a LIMIT BUY, rounding the ask up to the supplied rupee tick.
- Requires current control version/session, an eligible post-Resume signal,
  fresh bridge lease/source, reconciliation, contract timestamp, quote and funds.
- Computes an explicitly SYNTHETIC reservation against 50% of synthetic cash,
  including the existing per-entry buffer. This is not real money or debit proof.
- Commits the staged intent, reservation, disabled adapter request, audit event and
  PAUSED control update in ONE SQLite transaction in ONE isolated database.
- Rechecks clock, controls, stop generation, health and funds before commit.
- Rollback removes all staged rows after a precommit interruption. A lost response
  after commit leaves the complete plan; duplicate replay returns historical status
  without a new hold. Changed payload for the same signal conflicts.
- Startup remains PAUSED. Unresolved staged plans block Resume/reconciliation and
  another staged preparation; their holds survive restart and session rollover.

There is NO submission boundary that can send: submit() always raises. There are
no adapter attempts, broker receipts, simulated orders or simulated fills. No
release/cancel implementation is provided; staged holds are retained, never used
as evidence for release of real funds.

## Separation from the installed workspace

The existing allocation module explicitly accepts only simulator instruments.
This package preserves that rule. It does not put real-format keys into simulator
allocation tables or fabricate simulator fills. Instead the new isolated DB has
staged_intents, staged_reservations and staged_adapter_requests tables alongside
installed controller control/health tables.

Creation requires a fresh directory; recovery requires its exact staging marker.
There is no argument accepting an application database path. The active workspace,
closed live adapter and signed account review DB are not opened by the demo.
Do not point the application/legacy simulator Service at the staged DB.

The wrapper uses installed Service commands, with guards against Resume when a
staged plan exists. This is NOT installation into the normal application, UI,
background reader or real execution port. It does not claim a production-atomic
control/transport boundary. No transport exists here. Reusing installed health
and reconciliation code validates wiring in staging; their evidence is synthetic.

## Honest evidence limits

The demo uses a fixed synthetic session: 26 October 2026, 09:25 IST. NSE_FO|12345,
its expiry/lot metadata, quotes, lease and INR100,000 cash are EXPLICIT FIXTURES,
not verified actual instruments or real account cash. No date rewrites are needed
when running the fixture on a later day.

Draft staging freshness limits: signal 60s, reconciliation/funds/contract 30s,
quote 5s; spread <=5% of ask. Bridge health uses existing 15s heartbeat and 390s
source limits. These are test-stage rules, not a frozen production trading policy,
exchange calendar check, real quote-quality certification or approved live SLA.
Live metadata provenance, authoritative real cash, daily-loss limits and real
market/session validation remain gates before production.

Every result has orders_sent=false, production_execution_enabled=false,
entry_permission=false, strategy_ownership_verified=false,
real_funds_reservation_verified=false, reservation_release_permission=false,
live_contract_verified=false. Staging results must never be imported into the live
intent assessor or relabelled as LIVE_CLOSED broker attempts/receipts.

## Ubuntu VM validation

Extract the ZIP in ~/RB-ITOS-AI. Only hilega-production-staged-preparation/ is added.
Do not run an installer, alter dependency hashes or restart anything.

```bash
cd ~/RB-ITOS-AI
set +e
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-production-staged-preparation/test_preparation.py
```

After the focused tests pass, run the synthetic demonstration with a fresh output
directory. It must NOT already exist:

```bash
PYTHONPATH=backend:. .venv/bin/python -u \
  hilega-production-staged-preparation/demo.py \
  --output data/research/hilega-staged-preparation-demo-v1
```

Expected: status PASS, seven checks passed, one staged intent/reservation/request,
zero simulator orders/fills and every execution/ownership/release flag false.
The staged synthetic reservation is INR6,600.00, preserved on restart.

Share pytest's summary and demo stdout. No credentials, account pin or broker
access is required. Avoid pasting raw database contents.

Regression checks on installed controls/health can then run on the VM:

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  tests/test_hilega_production_control_foundation_v1.py \
  tests/test_hilega_production_bridge_health_v1.py
```

Author checks: static review and Python AST syntax parsing ONLY. No imports, tests,
demos, broker calls or application mutations were executed locally.

## What remains after this stage passes

- Production installation/integration with real strategy signals and authoritative
  broker metadata, contracts/quotes, controls, health, cash and risk evidence.
- Review/implement real reservation/debit/reflection handling; daily-loss settings.
- Genuine transport attempt/receipt provenance, ambiguity/restart recovery and
  verified acknowledgement -> fills -> positions scoped to strategy ownership.
- External Upstox exits, real partial-entry cleanup, manual exits and no-oversell.
- Fresh terminal-flat proof before exactly-once release of real reservations.
- Actual position/P&L UI, market-hours shadow validation, operational readiness,
  alert/escalation and backup/rollback checks.
- A separately authorized supervised pilot after required readiness gates pass.

This package does not resolve the observed empty live adapter (0 requests,
0 attempts, 0 receipts) or invent live evidence to bypass that blocker.
