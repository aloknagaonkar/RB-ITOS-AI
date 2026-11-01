# Closed worker-hook candidate v1: quick development checks, full release gate

## Current stage and why

The VM reported 163 passing cases for the exit-first reversal and partial-exit
fixture policy. This milestone packages a closed worker boundary and validates
startup/heartbeat, restart, graceful shutdown and stage cleanup before any managed
service installation. The actual application worker has not been patched or
hooked by this package.

To accelerate iteration, default validation uses 13 relevant cases plus read-only
systemd unit verification and two bounded closed-worker process probes. It checks
that all 38 baseline source files still match the passing implementations and
preserves the distinction between prior full evidence and fresh targeted evidence.
No fresh full-regression PASS is claimed by the quick mode.

## Quick command (development default)

Place the ZIP in the checkout, then:

```bash
cd ~/RB-ITOS-AI
unzip -n hilega-closed-worker-hook-v1.zip
.venv/bin/python hilega-closed-worker-hook-v1/apply_and_test.py --repo "$PWD"
```

Expected pytest count: **13** (eight new cases plus five selected recovery/policy
cases). The runner then stages a unit, runs `systemd-analyze --user verify`, and
runs a two-tick watch plus a one-tick restart probe directly as short-lived
processes. These are not managed service starts. It leaves the source/unit/health
artifacts in a new private hilega-closed-worker-stage-* directory for review.

Quick output is QUICK-VALIDATION.json with PASS_TARGETED_ONLY if all checks pass.
Actual VM test/probe results are pending; local checks here cover syntax and ZIP
integrity only.

## Full command (checkpoint/deployment gate)

```bash
.venv/bin/python hilega-closed-worker-hook-v1/apply_and_test.py --repo "$PWD" --full
```

Expected pytest count: **171** (the prior 163 plus eight new cases). Its result is
FULL-VALIDATION.json with PASS_FULL only if the full set and staging/probes pass.
Repeat the full run after core changes, a new checkpoint, or before deployment;
use targeted checks while iterating on isolated operational plumbing.

## Worker boundary

fixture_closed_worker.worker_tick() returns EXECUTION_HANDOFF_CLOSED_IN_CODE by
default. It opens no application DB, loads no token and sends no broker request.
Python tests may inject only the exact V2 OFFLINE_FIXTURE consumer; that connection
is tested with real candidate fixture processing. The CLI never supplies it, and
has no env/CLI switch enabling fixture or production execution.

The standalone CLI supports --once, --watch and --check. An optional health file
must be in a pre-existing private directory. Heartbeats are private atomic JSON
files bound to the worker source hash, run ID, freshness and closed authority
flags. TERM/INT publish STOPPED; bounded successful runs publish COMPLETED. Health
check requires RUNNING and a fresh heartbeat. This is heartbeat evidence, not an
independent process-liveness or trading-readiness guarantee.

The staged user unit has a literal absolute WorkingDirectory (without the quotes
that broke the earlier unit), quoted ExecStart args, UMask=0077,
NoNewPrivileges=yes and Restart=on-failure. It references only the closed script
and new private health path. No EnvironmentFile, token, DB or strategy path is
passed. The script uses no broker SDK in its CLI path.

## Installation scope and cleanup

The installer verifies package hashes, semantic parity of the 38 baseline sources
and the existing 163-case PASS report. It adds only fixture_closed_worker.py,
stage_closed_worker.py and test_closed_worker_hook.py under HOME, refusing to
overwrite differing files. All existing runtime/candidate sources remain intact.

No unit is copied into systemd configuration. No service is installed, enabled,
started, stopped or restarted. Existing application/companion services are not
controlled. Candidate tests use temporary synthetic DBs; the CLI probes open no
application databases. Production execution remains false.

Stage cleanup is available for this package's owned, non-running stage only:

```bash
.venv/bin/python hilega-closed-worker-hook-v1/stage_closed_worker.py --remove-stage /absolute/stage/path
```

It verifies the marker/source hashes, refuses unknown files/symlinks and running
health state, removes only the owned stage artifacts, and does not uninstall or
control any service. The cleanup behavior is tested against an unrelated-file
sentinel. Keep the validation reports/checkpoints separately.

## Next step

After successful validation, review the staged unit and connect the closed
boundary to the actual application worker with current source/service evidence.
Live execution activation, immediate opposite entry, automatic residual SELL,
cancel/reprice and production partial-fill policies are still pending. Production
authority, real network checks, operational deployment/rollback gates and an
explicitly authorized funded pilot remain separate.
