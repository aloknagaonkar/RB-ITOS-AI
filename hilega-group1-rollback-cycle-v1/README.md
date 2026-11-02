# Group 1 — controlled rollback and identical candidate restore

Default preparation is read-only for application services, installed code and live databases. It verifies current status, retained real backups and the original 314-case validation receipt, then prepares an exact cycle plan and eight new helper tests. The earlier 314 cases are not rerun.

    .venv/bin/python hilega-group1-rollback-cycle-v1/manage.py --repo "$PWD" --original-plan "$PWD/hilega-group1-rollout-plan-nvnouzgc/PLAN.json" --approved-plan-sha256 ef2b637dd6bdebf57bf03b56b4020cd39ab6735e8a9434e002dc452792dedcc6

The preparation creates a new reinstall-plan folder containing byte-for-byte copies of the unchanged approved PLAN.json and CHECK-VALIDATION.json. VALIDATION-PROVENANCE.json explicitly records the original source and hashes and that tests were not rerun. No validation fields or plan inputs are changed. The existing rollout code supports reuse of an already installed identical immutable bundle.

After reviewing the concrete CYCLE-PLAN.json, execution is:

    .venv/bin/python hilega-group1-rollback-cycle-v1/manage.py --repo "$PWD" --action execute --cycle-plan /absolute/review/CYCLE-PLAN.json --approve-cycle-sha256 EXACT_REPORTED_CYCLE_DIGEST

Execution calls only the verified original rollout tool using its unchanged approved plan digest:
1. hold original plan (stop all six application services)
2. rollback original worker code
3. start and status old closed worker
4. apply the identical plan in the new folder (stop services again, make fresh backups, reuse identical immutable bundle and install same wrapper)
5. start and status the restored candidate

This entails two maintenance windows. The controller remains paused and lifecycle tables must stay empty. No database restore or cursor rewind is performed. New leases are required for both old and candidate starts, and cursor sequence must not regress. All real backups and both transaction histories are retained.

On failure, the helper stops its sequence and records the failed action and original/reinstall plan locations. It does not automatically guess a recovery or retry the whole cycle. Inspect RESULT.json, CYCLE-TRANSACTION.json and the original rollout transaction records first.

After success, RESULT.json identifies the NEW active plan folder. Use that folder for future status/actions; the original transaction now records its completed rollback. The approved plan bytes and SHA256 remain identical.

This verifies rollback/restore for the closed source-worker deployment only. It does not enable an execution factory, enroll live ownership, resume the controller, certify full repository/service dependencies or validate broker trading. Groups 2 and 3 remain pending. Behavioral tests are VM-only.
