# Ownership-record maintenance v1

Installs the validated signed ownership-record modules and updated closed exit dispatcher. No production producer, SELL submission or reservation release is enabled.

## Prerequisite

Retain the corrected hilega-ownership-record-integration-tools-v1 directory and its passing VM report. The exact integration manifest SHA256 is 030a3e5817735423d1cd11b6f54740b118f6a1be45cb739a6f3439d94857ba67. The maintenance script verifies the staged files, passing 140-test proof and integration flags, installed baselines, paused safety, empty execution/preparation/reservation state, process identities and API health.

## Run on VM

```bash
cd ~/RB-ITOS-AI
.venv/bin/python -m zipfile -e \
  hilega-ownership-record-maintenance-v1.zip \
  hilega-ownership-record-maintenance-tools-v1

.venv/bin/python -W error::ResourceWarning -m unittest discover \
  -s hilega-ownership-record-maintenance-tools-v1 \
  -p 'test_maintain.py' -v &&
.venv/bin/python hilega-ownership-record-maintenance-tools-v1/maintain.py check &&
.venv/bin/python hilega-ownership-record-maintenance-tools-v1/maintain.py apply &&
.venv/bin/python hilega-ownership-record-maintenance-tools-v1/maintain.py verify &&
PYTHONPATH=backend:. .venv/bin/python check-preparation-paused.py
```

36 maintenance tests passed locally. Maintenance execution and post-deployment verification on your VM remain pending.

## Apply behavior

- Stop exactly the existing systemd user worker, API and production-source-worker units after matching their managed process inventory. Confirm no detached application processes remain.
- Recheck paused database safety and source pins after stopping.
- Create a private backup under backups/hilega-ownership-record-maintenance-* with transaction state, original exit_dispatch.py and the original absence of the eight added modules.
- Install exactly nine validated runtime files. source.py, cash reservation policy, broker transport and account adapter are unchanged. New package directories are checked for symlinks before creation.
- Restart worker, API and source units, update the existing maintenance PID identities and verify exact installed hashes, paused safety, empty activity, closed API/adapter and unchanged allocation policy.
- Report OWNERSHIP_RECORD_DEPLOYED_PAUSED_VERIFIED with the backup path.

No .env, strategy or systemd configuration is changed. No database migration is performed. Ownership tables are created only by a later explicit producer invocation; that producer is not connected or enabled here. Missing ownership tables leave closed exit behavior unchanged. Existing nonempty ownership tables block this maintenance path for review.

## Explicit rollback

Use the exact backup path printed by apply:

```bash
.venv/bin/python hilega-ownership-record-maintenance-tools-v1/maintain.py rollback \
  --backup /home/aloknagaonkar46/RB-ITOS-AI/backups/hilega-ownership-record-maintenance-REPLACE_WITH_PRINTED_SUFFIX
```

Rollback validates the backup/proof/current code, checks paused database safety, stops the same three units, restores exit_dispatch.py and removes only the eight added source files, then restarts and verifies the original paused baseline. Empty directories or Python caches may remain; unrelated files and database records are not removed. Nonempty execution/reservation/ownership activity, corrupted backups or unrecognized source drift require review.

A file-write failure restores already changed files while services remain stopped. A startup failure triggers one stop request for the same units, records whether stopped state was confirmed and does not automatically restart or roll back. Inspect the transaction/output before another action; failure_cleanup_services_stopped=false does not confirm stopped services.

See GO_LIVE_CHECKLIST.md for completed work and pending production gates. Entry remains capped at 50% verified available cash including buffer, with no required daily loss limit. Live exit submission and reservation release remain disabled.
