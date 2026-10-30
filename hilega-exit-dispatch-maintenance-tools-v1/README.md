# Closed exit-dispatch maintenance v1

Installs the VM-validated durable refused-exit path. This adds application exit recording only. It does not implement live SELL submission or reservation release.

## Prerequisites

Keep hilega-exit-dispatch-closed-tools-v1 in the repository with its original files and passing CLOSED_EXIT_DISPATCH_REGRESSION report. The maintenance script pins manifest SHA256 833990b9eabc3f57d8a382638ba134d824937d9109499582f4dd6291689ec72d and verifies the report and every installed baseline before proceeding.

The application must be paused on PREPARATION_ONLY, with no execution, preparation, adapter activity or local cash reservations, and a fully consumed verified journal. After-hours stale market source is permitted by the existing paused-safety checker. Three systemd user units and their managed process identities must match. No broker credentials or broker reads are needed.

## Run

Upload this ZIP to ~/RB-ITOS-AI, then:

```bash
cd ~/RB-ITOS-AI
.venv/bin/python -m zipfile -e \
  hilega-exit-dispatch-maintenance-v1.zip \
  hilega-exit-dispatch-maintenance-tools-v1

.venv/bin/python -W error::ResourceWarning -m unittest discover \
  -s hilega-exit-dispatch-maintenance-tools-v1 \
  -p 'test_maintain.py' -v &&
.venv/bin/python hilega-exit-dispatch-maintenance-tools-v1/maintain.py check &&
.venv/bin/python hilega-exit-dispatch-maintenance-tools-v1/maintain.py apply &&
.venv/bin/python hilega-exit-dispatch-maintenance-tools-v1/maintain.py verify &&
PYTHONPATH=backend:. .venv/bin/python check-preparation-paused.py
```

The 32 maintenance tests passed locally. The runtime patch separately passed 10 transaction tests and 90 application/regression tests on your VM. The maintenance commands must still be executed on the VM.

## What apply does

1. Verify exact staged code, passing VM proof, installed baselines, paused safety, empty activity, API health and systemd/process inventory.
2. Write a private transaction record and backup directory under backups/hilega-exit-dispatch-maintenance-*.
3. Stop exactly hilega-worker.service, hilega-api.service and hilega-production-source-worker.service. Confirm all managed and detached application processes are stopped.
4. Recheck database safety and baselines. Back up source.py, record that exit_dispatch.py was absent, then install exactly the two validated files using atomic writes. A file-write failure restores already changed files while services remain stopped.
5. Start worker, API and source services. Refresh the existing maintenance process identity record, preserving its original backup, and verify paused safety, closed adapter and API, exact installed hashes and no execution/reservation activity.
6. Report CLOSED_EXIT_DISPATCH_DEPLOYED_PAUSED_VERIFIED with the backup path and new processes.

No .env, strategy, systemd configuration, entry allocation or daily loss settings are changed. No database migration is performed by maintenance. The runtime creates its exit-record table lazily if a later confirmed exit is processed. No historical exits are replayed or backfilled.

## Failure and explicit rollback

The script does not retry a failed deployment or automatically roll back after startup failure. If startup fails, it requests one stop of the same three units and records whether their stopped state was confirmed. Inspect the output and transaction record before taking the next action; do not assume the services stopped if failure_cleanup_services_stopped is false.

For a deliberate rollback, use the exact backup path printed by apply:

```bash
.venv/bin/python hilega-exit-dispatch-maintenance-tools-v1/maintain.py rollback \
  --backup /home/aloknagaonkar46/RB-ITOS-AI/backups/hilega-exit-dispatch-maintenance-REPLACE_WITH_PRINTED_SUFFIX
```

Rollback verifies the transaction, original backup hashes, current code against the original or validated versions, process scope and paused database safety. It stops the three units, restores source.py, removes the newly added exit_dispatch.py, restarts and verifies the original baseline in paused mode. Unrecognized code drift, nonempty execution/reservations or corrupted backups block rollback. Exit audit records, if any, are retained in the database. A failed rollback startup also requests a stop and records the confirmed outcome.

A successful apply keeps production_execution_enabled=false, reservation_release_permission=false and live_exit_submission_integrated=false. Entry remains capped at 50% verified available cash including buffer, with no required daily loss limit.
