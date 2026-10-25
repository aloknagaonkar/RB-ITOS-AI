# Consolidated execution-port library and closed-gate status

Staged application package. Production stays disabled. Existing simulator controls,
strategy, reader, worker and execution route are unchanged. No activation switch.

## What is consolidated

A single backend package `market_lab.hilega_execution_port_v1` contains the checked
request mapper, closed HTTP/injected adapter, controller reservation link,
ownership evidence link and exactly-once release consumer. Imports are package
relative: the installed library no longer dynamically loads earlier research
folders or depends on their fixture helpers. It reuses the installed controller,
allocation and ownership modules as pinned dependencies.

`ClosedPort` provides creation/recovery, synthetic funding, next-fresh Resume,
entry preparation, explicit fixture fills/cancellation/exit, offline reconciliation
and release through one API. Its controller subclass captures the reservation/
intent boundary without temporary monkeypatching. Synthetic fixture lifecycle
and closed HTTP gate modes remain strictly separate. It cannot attach to the
normal active workspace database.

The workspace API/UI gains read-only availability and CLOSED_IN_CODE status.
That status means library installed, NOT active production routing or readiness.
No UI/CLI control is redirected to a new execution backend in this package.

## Important limits before testing

- Real HTTP mutation gate remains unconditionally closed before token/network.
- Only isolated synthetic cash and contract evidence; real cash is NOT wired.
- Fixture trade/position evidence remains explicit offline evidence, never live.
- Port's broker fixture supports one lifecycle; after settlement, legacy simulator
  Resume remains blocked. Multi-cycle broker projection/routing is NOT implemented.
  Do not bypass that check or point the running application at fixture databases.
- SimBroker fills are never fabricated from adapter acknowledgements.
- Real fill ownership, external exits, P&L, live release and live readiness remain
  pending. This is a consolidated library promotion, not production activation.

## Stage on VM

Extract/sync this folder into the repository root:

```bash
cd ~/RB-ITOS-AI
set +e
.venv/bin/python hilega-production-consolidated-port/install.py \
  --stage data/research/hilega-consolidated-port-stage
```

After STAGED:

```bash
.venv/bin/python -u hilega-production-consolidated-port/validate.py \
  --stage data/research/hilega-consolidated-port-stage \
  --output data/research/hilega-consolidated-port-validation.json
result=$?
echo "Validation exit code: $result"
```

Validation runs the consolidated port and adapter tests plus installed controls,
workspace, allocation, ownership, health, bridge and strategy regressions. It runs
four synthetic demos and builds the staged frontend. All commands run on staged
code, with broker observation/reader disabled and shell secrets removed. No
services start and the active application remains unchanged. Only AST parsing
was done in authoring; all runtime verification is pending on your VM.

Source hashes guard the applied durable-integration baseline. Previous corrected
central allocation tests are preserved. Use fresh staging/output paths; share any
mismatch or failure rather than changing hashes to bypass it.

## Apply after PASS only

```bash
.venv/bin/python hilega-production-consolidated-port/install.py --apply \
  --validation data/research/hilega-consolidated-port-validation.json
```

Installer requires optional simulator reader disabled, simulator PAUSED, no
pending/unknown orders, no exposure and no held allocation. It backs up replaced
files and records package-created files for rollback. It does not change strategy,
core controller, cash settings, environment, database or service state.
After APPLIED, build frontend and use the existing safe UI/API restart only.
Do not restart strategy workers for this library/status update.

Retain the reported backup and rollback.json. Rollback restores replaced files
and removes only package-created files, with reader disabled and simulator flat/
paused, then rebuilds frontend and safely restarts the UI/API. No DB migration or
destructive table removal is needed for the active workspace.

## Required next engineering gates

Multi-cycle broker projection/reconciliation routing; fresh verified real account
and allocation input; actual broker lifecycle and partial/manual/external exits;
real debit/reflection and charges; contract/quote/risk checks including daily loss;
operational readiness/alerts and market-hours shadow validation; separately approved
controlled pilot. No test PASS in this package enables real execution.
