# Guarded application CODE deployment and rollback

This package prepares the next step after the user's staged application run:
151 tests passed, 2 dependency deprecation warnings, 39.16 seconds.
The release is the application-preparation package whose manifest SHA256 is
4754916d28da64ea12f8b1186365ad9b7a0f27793e982c065f127cc90bea54f7.
This tool does not rerun or independently attest those 151 results. It checks the
local PASS report, stage, source/dependency hashes and exact release identity.

## PID-managed deployment update

The VM inventory identified market_lab.runtime worker (observed PID 1149) and
market_lab.runtime api (observed PID 10478), matching data/runtime/worker.json
and api.json and this repository. PIDs are observations, never constants for a
future kill command. The two systemd server:app services run from ~/bridge and
are unrelated. Strategy observers, collectors and sandbox workers are outside
this deployment's stop scope.

The original tool's systemd-only quiescence guard does not fit this deployment.
The update adds an explicit --process-mode pid-managed alternative; it does not
remove the systemd default or allow unrelated units to satisfy the guard.
The application release, manifest and prior 151-test validation are UNCHANGED.
Only deployment tooling/tests/instructions have changed.

Run these updated tool tests on the VM (no real process signals are used):

```bash
cd ~/RB-ITOS-AI
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-production-application-deployment/test_deploy.py \
  hilega-production-application-deployment/test_managed_processes.py
```

Then run the read-only check for the actual process model:

```bash
.venv/bin/python hilega-production-application-deployment/deploy.py check \
  --process-mode pid-managed
```

The check includes safe identities from /proc and the two repo-owned PID records.
Running API/worker processes are expected at this point; apply_ready stays false.
It prints no full command line, environment or credentials. It sends no signals.
Duplicate roles, mismatched PID records or unreadable identity require review.

For a later authorized apply/rollback, --process-mode pid-managed requires NO
--unit arguments. It rechecks that no API, general runtime worker or production
source worker is running from this repo, both initially and before every file
mutation. PID records must remain present for identity review; do not use broad
scripts/stop.sh, remove PID files or stop all Python processes. Exited zombies
cannot read code and do not count as running workers. Unrelated repo processes
and historical/research runtime subcommands are not selected for stopping.

No stop/start automation is included. The final reviewed maintenance sequence is:
1. Reverify current PID identities and canonical API/worker launcher/configuration.
2. With explicit authorization, gracefully stop ONLY those affected processes,
   retaining their PID records; ensure no scheduler/supervisor will respawn them.
3. Run the existing guarded code-only apply with pid-managed mode. All original
   release/report/hash, paused/empty DB, backup/journal and route checks remain.
4. Verify applied source, then restart only the approved API/worker using the
   confirmed launcher configuration and existing logs. Verify API health and
   SIMULATOR/PAUSED state. PREPARATION_ONLY activation is still separate.

The process scan is not an OS-wide maintenance lock. Operator attestation still
covers disabled respawn sources/manual launches and complete process ownership.
A newly spawned relevant process causes a per-file guard to stop the deployment;
the journal/backup supports reviewed recovery, not automatic service restart.

The rest of this document describes the original guards and the systemd option.
Where it mentions a required unit list, that applies only to systemd mode; for
this VM use the explicit pid-managed mode after the required authorization.

## Scope

Ten application files: three replacements (controller core, workspace API module,
existing source-worker script) and seven additions (runtime modules/dependencies
and application-integration tests/fixture). No strategy rule file, .env, service
unit, account pin, token, application DB or market-data cache is modified.

Default check is read-only. apply and rollback are explicit separate code actions.
No action stops/starts/restarts services, changes route configuration or enables
live orders. The current stage is deployment preparation, NOT permission to apply.

Only static review and Python AST parsing were performed by the author. Tests
below must run on the Ubuntu VM. No local tests, systemd calls, deploy or rollback
were run by the author.

## Run these now: tool tests and read-only deployment check

Extract this ZIP into ~/RB-ITOS-AI; it adds
hilega-production-application-deployment/. Keep the existing application-preparation
release package, validated /tmp stage and validation report in place.

```bash
cd ~/RB-ITOS-AI
PYTHONPATH=backend:. .venv/bin/python -m pytest -q \
  hilega-production-application-deployment/test_deploy.py
```

After those tests pass:

```bash
.venv/bin/python hilega-production-application-deployment/deploy.py check
```

Defaults:
- release: hilega-production-application-preparation/
- validated stage: /tmp/hilega-app-preparation-stage-v1
- PASS report: data/research/hilega-app-preparation-validation-v1.json
- workspace DB: data/research/hilega-production-workspace/sim.sqlite
- root: current repository directory

The check validates packaged and staged files, the pinned manifest, report/model/
PASS/returncode/flags, unchanged dependencies and current destination hashes.
It also verifies that the selected shell/.env route is still SIMULATOR, workspace
mode is DISABLED or SIMULATION_ONLY, workspace control is PAUSED, execution tables
are empty, no preparation enrollment/plans/holds/outbox exist and there is no
unhandled stop generation. It reads the DB via SQLite read-only/query_only.
It never prints credentials, account identities, complete environment or DB rows.

Current output should show three replacements, seven new files, no source changes,
production_execution_enabled=false and apply_ready=false. Stopped services and
complete process ownership have NOT been proven by a read-only code check.
A blocked check needs review; do not change hashes, delete history, remove a
route pin, edit controls or clear holds to bypass it. Different strategy/research
files outside the release/dependencies do not by themselves block this rollout.

Candidate service discovery (also read-only):

```bash
.venv/bin/python \
  hilega-production-application-deployment/discover_services.py
```

This lists matching service names/states only; no command lines/environment and
no control actions. It is a candidate list, not proof that all API/worker/cron/
manual processes were found. If names do not match, the owner must identify the
actual process supervisor. Do not guess service names or stop unrelated services.
Share the test summary and both read-only JSON outputs.

## Reviewable deployment procedure — do not execute yet

1. Confirm the exact release/stage/report match and review the three source diffs.
   Verify active app configuration, including systemd Environment/EnvironmentFile
   or other supervisor config; the code check only sees this command's shell/.env.
2. Identify every API/strategy-reader/simulator/preparation worker using this code
   and DB, its actual supervisor and any activation sockets/timers. Account for
   manual processes and scheduled jobs. Application control must already be PAUSED
   using the existing authenticated control mechanism.
3. Choose a maintenance window. Obtain explicit authorization for CODE APPLY and
   service handling. Stop the reviewed processes via their actual supervisor.
   Nothing here performs that stop. Confirm no process can respawn through another
   supervisor or write source/DB concurrently. --services-stopped is an operator
   attestation, not automatic discovery or a substitute for that review.
4. The later apply command requires action=apply, --services-stopped, the complete
   --unit list and --confirmation APPLY_VALIDATED_CODE_ONLY. Each selected systemd
   unit must exist and be inactive/failed; any TriggeredBy unit must also be
   included and inactive. No automatic stop/restart is performed. Non-systemd
   deployments need a separately reviewed quiescence check; do not bypass this one.
5. Under a deployment file lock, apply revalidates all guards, saves original files
   and permissions in a private timestamped backups/hilega-application-code-* folder,
   fsyncs a deployment journal, then replaces individual files atomically.
   Multi-file deployment is NOT atomic. Processes must stay stopped throughout.
6. Apply leaves services stopped and shell/.env unchanged with SIMULATOR route.
   It does not enroll PREPARATION_ONLY. Post-apply source verification, restart and
   route activation require their own reviewed instructions and authorization.

The apply command is deliberately not included as a copy/paste instruction in the
current validation sequence. The tool's --help exposes its explicit arguments for
that later authorized action. Merely pulling/extracting either package does not
apply its files/ overlays to the app backend.

## Backup/recovery/rollback behavior

The durable deployment.json records exact root, release fingerprint, old/new file
hashes, preserved modes, validation-report hash and phase. Original code files are
saved before the first replacement. No DB/environment/credential backup is claimed.
The first future PREPARATION_ONLY enrollment needs a separate consistent data and
configuration backup/recovery plan; this code-only tool cannot reverse it safely.

If interrupted during apply, the journal is marked
INTERRUPTED_REQUIRES_ROLLBACK (or may remain APPLYING after a hard process loss).
Do not restart against mixed code or blindly rerun apply. Preserve the backup and
review a code-only rollback. There is NO automatic rollback after unknown external
edits and NO automatic service restart.

Later rollback requires action=rollback, the recorded --backup directory,
--services-stopped, reviewed --unit list and --confirmation ROLLBACK_CODE_ONLY.
It first validates every backup and target, root/release/file map, paused workspace,
empty execution/preparation state and unchanged SIMULATOR configuration. Targets
must still match the recorded old or new hash. A later user edit blocks rollback
before any source file is changed. Unmodified new files are removed and original
files/modes are restored atomically per file. Recovery is idempotent; the journal
tracks ROLLING_BACK and ROLLED_BACK phases. Empty created directories may remain.

Rollback refuses a workspace that has PREPARATION_ONLY enrollment or any pending
plan/hold/outbox. Restoring old code while leaving a new route/data model could
hide safety state. Do not delete state or restore an arbitrary old DB to evade
that guard; data disposition and recovery must be separately reviewed.

## Completion criteria

- Tool tests pass on the VM.
- Read-only deployment check matches the validated release and reports no blocker.
- Actual API/worker supervision and restart/rollback plan are identified.

Only then is the code-apply action concrete and reviewable for authorization.
Live production activation is NOT part of that approval. Real cash reservations,
price/tick policy, broker acknowledgements/fills/ownership, exits, operational risk
controls and a supervised live pilot remain separate pending milestones.
