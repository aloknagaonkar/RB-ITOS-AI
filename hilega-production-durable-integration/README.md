# Durable controls integrated into the existing simulator workspace

Staged application update, SIMULATION ONLY. Uses the existing Service, authenticated
workspace API, UI/CLI command route, strategy Bridge and reader-health checks.
It does not install the separate standalone Controller as a competing service.
No strategy files, Upstox transports, real funds, token settings or workers change.

## Changes

- Commit synthetic reservation, entry intent and reservation event in one SQLite
  transaction. A failure inside that transaction leaves neither a hold nor an intent.
- Save a Pause/Flatten request before waiting for the shared control file lock.
  New entries see the pending request and are blocked. If a simulator order was
  already accepted, the existing cancellation/cleanup lifecycle handles its fills.
- Keep stop requests durable across API/reader recovery, deduplicate repeated
  command IDs, preserve version/session checks and existing ownership/health gates.
- Display pending-stop generation and handled generation in the existing workspace.
  Start is disabled while the server reports a pending stop.
- Existing CLI controls use the same API/Service and need no new syntax.

A Pause request is not a claim that an accepted order was undone. Established
positions remain on Pause; Exit/Flatten is used to close them. Handled generation
means the server has durably blocked entries and marked pending orders for cleanup;
use the overall status and positions to determine whether cancellation/exit is done.

## Stage and validate on the VM

Extract this package into the repository root (or sync its folder through Git).
The installer requires the previously installed central-allocation runtime hashes.
It does NOT overwrite the central-allocation tests you corrected on your VM.

```bash
cd ~/RB-ITOS-AI
set +e
.venv/bin/python hilega-production-durable-integration/install.py \
  --stage data/research/hilega-durable-integration-stage
```

Only after STAGED:

```bash
.venv/bin/python -u hilega-production-durable-integration/validate.py \
  --stage data/research/hilega-durable-integration-stage \
  --output data/research/hilega-durable-integration-validation.json
result=$?
echo "Validation exit code: $result"
```

Validation runs the new integration tests and existing control, workspace,
allocation, ownership, bridge, heartbeat and strategy regressions. It then runs
three synthetic demos and builds the staged frontend. Tests/demos use staged code
and working directory with broker observation/reader disabled and shell secrets
removed. No services start. Source authoring checks were AST parsing only; all
runtime verification must happen on your VM.

Use a fresh staging path. Do not edit manifest hashes to bypass a source mismatch;
provide the mismatch output so the installed changes can be reviewed.

## Apply only after PASS

```bash
.venv/bin/python hilega-production-durable-integration/install.py --apply \
  --validation data/research/hilega-durable-integration-validation.json
```

Apply requires the optional simulator reader flag disabled, simulator PAUSED,
no pending/unknown simulator orders, no simulator exposure and no held allocation.
It backs up every replaced file and records newly created files in rollback.json.
It never changes the simulation DB, environment, strategy or services during apply.
Actual Sandbox/broker positions are outside this installer; no stop/start of those
workers is performed. Follow the existing safe UI/API restart procedure after a
successful frontend build; do not restart strategy workers for this update.

Keep the reported backup directory. Rollback restores the listed existing files
and removes only package-created files after stopping the optional simulator reader
and confirming simulator flat/paused. Rebuild frontend and use the safe API restart.
The new SQLite stop tables are additive and do not need destructive removal.

## Limits

No real order submission, production enable switch, external broker-exit handling,
real cash reservation, daily loss limit, multiple-contract execution or live P&L.
Pending stop visibility is still subject to the UI receiving a current server
response; the durable server-side veto does not depend on browser refresh.
This change adds transaction/stop mechanisms to the installed application service;
it does not claim all tests of the standalone prototype establish app behavior.
The VM regression results must pass before applying.
