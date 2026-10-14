# HILEGA strike safety update — VM verification required

This package updates the uploaded RB-ITOS-AI-feature-updated.zip code. It does not
activate ranked selection, create policies, change .env/control, arm, run tests,
build or restart services. No local tests or application Python were executed.
The strategy's 14:55 cutoff stays unchanged. Live execution stays disabled.

Changes:
- verified, causal, trade-specific manual-reset replay; blocked history stays blocked;
- mode changes decline new entries without stopping known position exits;
- durable versioned contract + quantity plans and quote-age rechecks;
- known pre-order failures become no-trade with harmless later exits;
- RANKED_OBSERVATION_ONLY accepts an explicitly unapproved demonstration policy,
  records every candidate, and places no entries;
- new arms enable automatic confirmed-fill reconciliation, partial BUY cancellation,
  residual SELL attempts, deterministic-tag recovery and bounded exit retries;
- old untagged journals/already-armed sessions retain legacy ACK semantics;
- dashboard candidate reasons and requested/filled/remaining quantities;
- complete research coverage denominator, frozen-contract manifest, common-five
  comparisons, MAE/MFE and explicit cost/slippage scenarios.

## Transfer and check

Extract this package into ~/RB-ITOS-AI so this file is located at
hilega_strike_safety_update/README.md. git pull cannot retrieve these uncommitted
files. Do not copy the whole original ZIP over an active working repository.

```bash
python hilega_strike_safety_update/install.py --check
```

The installer validates exact before/after file hashes. If the VM still has the
pre-selector code rather than the uploaded ZIP version, it may refuse with
SOURCE_HASH_MISMATCH. Share that output so the patch can be adapted to the VM's
actual files; do not bypass the guard or overwrite unrelated changes.

## Run staged tests before installation

The supplied conftest uses patched modules plus unchanged VM dependencies, without
writing backend files. From the repo root:

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega_strike_safety_update/files/tests/test_hilega_strike_selector_v1.py \
  hilega_strike_safety_update/files/tests/test_hilega_upstox_sandbox_basket_v2.py \
  hilega_strike_safety_update/files/tests/test_hilega_sandbox_event_bridge_v1.py \
  hilega_strike_safety_update/files/tests/test_hilega_sandbox_fill_ledger_v1.py \
  hilega_strike_safety_update/files/tests/test_hilega_strike_ranking_research.py
```

## Apply only while flat

Check status and confirm no open legs, uncertain requests, pending fill orders or
existing safety blocks. Legacy ACK-based flat status is not actual broker proof;
use order evidence/manual reconciliation where needed. Stop only the separate
Sandbox worker, then apply:

```bash
bash scripts/status_hilega_upstox_sandbox_worker.sh
bash scripts/stop_hilega_upstox_sandbox_worker.sh
python hilega_strike_safety_update/install.py
npm --prefix frontend run build
```

The installer refuses an active Sandbox worker or journal positions/uncertainty
and creates a backup. If tests/build fail, leave the worker stopped and send the
output. Do not restart or arm to work around a failure.

After applying, repeat the focused tests against installed backend modules:

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  tests/test_hilega_strike_selector_v1.py \
  tests/test_hilega_upstox_sandbox_basket_v2.py \
  tests/test_hilega_sandbox_event_bridge_v1.py \
  tests/test_hilega_sandbox_fill_ledger_v1.py \
  tests/test_hilega_strike_ranking_research.py
```

Also verify manual-exit compatibility using your existing VM suites. Those old
patch test loaders can intentionally prepend bundled modules; inspect their import
paths so a passing old bundle is not mistaken for verification of installed code.

After successful tests/build, restart only the API and Sandbox worker:

```bash
bash scripts/restart_api_only.sh
bash scripts/start_hilega_upstox_sandbox_worker.sh
bash scripts/status_hilega_upstox_sandbox_worker.sh
```

Do not use full restart.sh during market hours. No live-shadow restart is needed
for this update. Inspect automatic_fill_ledger_version after the next clean new
arm. Already-armed sessions stay legacy; do not force re-arm an open position.
Future worker premarket auto-arms will enable the ledger for the default five-leg
mode. Broker response parsing and partial/zero-fill behavior require VM validation
before restarting a production-observation worker.

## Research next

Read docs/hilega-ranked-strike-sandbox.md. The report now requires explicit
--round-trip-cost-rupees and --slippage-points-per-side arguments. Without a
historically verified --contract-manifest all accepted trades remain incomplete:
this is an honest data inventory, not a strike ranking.

No historical comparison was run here, no best strike is identified, and no policy
is approved. Observation mode or ranked execution requires a later separate
operator activation. Dashboard open P&L includes estimates; closed confirmed P&L
is gross of fees. This remains Sandbox-only and not validated as live-ready.
