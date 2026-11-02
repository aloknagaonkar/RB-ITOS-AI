# Recover the cache-blocked Group 1 candidate restoration

The original rollback passed. Candidate reinstallation stopped before stopping services or creating its transaction because normal Python __pycache__ files appeared inside the immutable bundle. This package repairs that exact state without changing any approved plan, manifest, source or wheel bytes.

Run on the VM's normal non-root account:

    .venv/bin/python hilega-group1-cache-recovery-v1/recover.py --repo "$PWD" --cycle-plan "$PWD/hilega-group1-rollback-cycle-review-50sy9biq/CYCLE-PLAN.json" --approved-cycle-sha256 c9cbbb88467a416fbb8968425de25bf63aba09d132a1492be195c176dc5b0ed5 --recover

Without --recover it performs only read-only checks and six tests. With --recover, after those pass it:
1. Requires the original transaction to be ROLLED_BACK_RUNNING, the candidate reinstall transaction to be absent, and the exact original plan/validation/backups/tools to match.
2. Verifies the old closed worker's current status, the full installed bundle manifest and every approved file hash.
3. Accepts only __pycache__/*.pyc extras that map to Python sources already in the approved manifest. Unknown extras, symlinks, hardlinked caches, missing or changed sources block repair.
4. Copies caches into a new auditable quarantine, verifies copies, then removes only those caches from the bundle. No approved file is deleted or rewritten.
5. Makes installed bundle files owner-read-only and directories owner-read/execute-only. Empty cache directories remain read-only. This prevents optional bytecode regeneration without changing source bytes, tool manifests, private configuration or plan hashes.
6. Runs the original approved reinstall plan's apply, start and status commands. This is one remaining service-stop/start window; the successful rollback is not repeated. New real backups are created by the original apply path. No database is restored or rewound.
7. Checks new lease, nonregressing source cursor, empty lifecycle state, no regenerated caches and manifest integrity. The result names the new active plan folder for future status/actions.

Failure stops the sequence and records the original tool output and transaction phase. Do not rerun after a candidate transaction starts without inspecting it. Existing audit folders, old cycle failure logs and real database backups are retained.

Six new tests include unknown-file rejection, changed source detection, cache provenance, quarantine preservation and an actual Python import from a read-only bundle without bytecode suppression. No behavioral tests are run in the packaging workspace. Prior 314-case closed release evidence is reused, not rerun. Future fresh release installation tooling must apply this read-only bundle policy before startup.

This repairs closed-worker deployment only. The controller remains paused, factory/ownership unenrolled and live execution disabled. Full repository/broker/trading readiness is not certified.
