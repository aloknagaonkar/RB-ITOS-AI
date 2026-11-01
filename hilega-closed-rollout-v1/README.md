# Reviewable closed-hook rollout tool

Current evidence: 212 candidate integration cases passed; the environment hash and selected database paths match the approved startup contract; the repeated read-only baseline reported no blockers. This package prepares a concrete rollout for three files only: Source, worker call site and the new routing guard. It does not configure execution sessions, provision production authority or enable trading.

## First VM command: check only

```bash
.venv/bin/python hilega-closed-rollout-v1/manage.py --repo "$PWD"
```

Default CHECK revalidates pinned source/packages and the current environment, requires an empty paused application/closed adapter baseline, verifies the existing tested stage, queries the six existing service states read-only, writes a private proposed PLAN.json and runs 12 synthetic maintenance tests. It does not stop services, create real database backups, approve the plan or install files. Share its JSON report before taking a maintenance action.

Keep all corrected previous folders/reports, including the successful effective-environment report and combined 212-case V2 report. Do not overwrite them with original ZIPs. The verified staged files must still exist. No local behavioral tests were run in the assistant workspace; syntax checks only.

## Reviewable maintenance implementation

The package includes separate apply, start, hold, rollback and cancel-before-install actions for review. They are NOT invoked by CHECK. Every maintenance command requires --plan pointing to the generated PLAN.json and --approve-plan-sha256 matching its exact current bytes, as well as a passed CHECK-VALIDATION.json for that plan. These explicit commands authorize only this closed code rollout; they never create execution authority.

* apply stops the six allowlisted user units that were active, verifies they are inactive with MainPID=0, rejects remaining repository Python/source processes, and rechecks the paused empty baseline.
* It creates private SQLite backup copies of both real databases and checks them, backs up the original code, then replaces exactly three pinned files. Services remain stopped after installation.
* start restores only previously active services, with the source worker last. It verifies active states, a new current source heartbeat/lease, no health error and a controller that remains PAUSED. A startup failure stops attempted starts for review.
* hold stops the allowlisted services for inspection/rollback. rollback restores pinned code and removes a newly created guard, refusing external edits. It leaves services stopped.
* cancel-before-install handles a stopped maintenance run that failed before file installation, verifies original code and marks it eligible for explicit original-code startup.

There is no automatic restart after an apply error. STOPPING/BACKING_UP failures require cancellation review; INSTALLING/installed/startup-failed phases support code rollback. Power loss may require inspection of leftover temporary files. Never delete unknown temporary files blindly.

Database backups are retained but are not automatically restored: rewinding a source cursor or ledger could replay history. Code rollback preserves the current databases. Actual database backup/restore disaster recovery is a separate review. The synthetic tests validate backup/rollback routines in disposable databases and mock service control, not real managed startup.

## Scope and remaining requirements

Installation requires an explicit maintenance window: all six allowlisted units may be unavailable until explicit startup. The tool does not write the old supervisor's config, .env or MIGRATION_APPROVED.json. It records a separate exact-plan approval only when an explicitly approved apply command is run. The startup configuration and environment hashes must still match before every action.

This is a closed preparation hook rollout. The coordinator execution factory is still absent; no candidate owner state is enrolled. Existing owner/coordinator tables or execution/preparation rows block installation and require migration review. Full production dependency reconciliation, full release regression, actual broker validation, authority/policy approval, fees/cash handling and a controlled funded lifecycle remain pending. Passing CHECK is not deployment or production readiness.
