# Closed release review V2: staged dependencies and consolidated blockers

Previous VM milestone: 207 candidate integration cases passed. Its only unresolved direct module was the staged market_lab.hilega_exclusive_closed_route_v1. The installed regular market_lab package hid the staged namespace directory from the static resolver. This revision fixes that inventory behavior without installing the guard or suppressing unresolved imports.

## Combined changes

* Explicit module-to-file mapping for staged Source, guard, coordinator and worker, with exact SHA256 validation before reporting resolution.
* Rejection of changed files, symlink/escaping paths, and scan text that differs from the pinned file.
* Existing service mapping, release-file plan, bounded closed startup and disposable-file rollback rehearsals retained.
* One DEPLOYMENT-BLOCKERS.json distinguishing passing evidence from missing deployment and production requirements.

Default validation runs 21 release-review cases (the prior 16 plus five focused resolver/checklist cases). Prior 207-case evidence is required and preserved. Optional combined candidate integration runs the previous routing/lifecycle tests with this revision, expected 212 cases. These counts overlap; do not add them as unique tests.

## VM commands

Keep all corrected previous folders, including hilega-closed-release-v1 and its successful combined 207-case VM-VALIDATION.json. Do not overwrite them with original ZIPs.

```bash
.venv/bin/python hilega-closed-release-v2/apply_and_test.py --repo "$PWD"
```

Expected: 21 cases, direct_unresolved_imports: 0. A nonzero unresolved count makes the runner fail even if pytest passes.

Optional combined integration:

```bash
.venv/bin/python hilega-closed-release-v2/apply_and_test.py --repo "$PWD" --integration
```

Expected: 212 cases. Full repository regression is not included. No behavioral tests ran in the assistant workspace; syntax checks only.

The report identifies a new review folder containing STAGED-MODULE-MAP.json, DIRECT-DEPENDENCIES.json, DEPLOYMENT-BLOCKERS.json, RELEASE-REVIEW.json, SERVICE-INVENTORY.json, staged source hashes and a bounded closed-probe unit. The unit is only syntax-verified, never installed or started. Startup tests invoke a closed CLI subprocess, not an actual systemd-managed worker.

## Boundaries

The resolver uses the explicit staged mapping only for those exact modules and verifies all mapped file hashes. Other imports still use static package resolution without executing package initializers. The scan covers declared direct imports, not full transitive runtime closure; dependency_manifest_fully_reconciled remains false. A zero direct-unresolved count does not mean deployment readiness.

The consolidated blocker report retains unfinished requirements: transitive release manifests, supervisor approval reconciliation, actual database/owner-state baseline, quiescence and backups, actual managed startup/rollback, execution-session configuration and trusted authority, broker/policy validation, fees/cash handling and full release regression.

No application sources are installed, no private configuration or live database is opened, no service control commands are issued and no live apply command exists. File replacement/rollback tests accept only explicitly marked disposable non-Git directories and never operate on the running application repository. Production execution stays closed.
