# Combined closed release preparation

Previous VM checkpoint: 191 combined candidate cases passed after the Source constructor-mock correction. Keep those corrected packages and their successful reports. This bundle combines the next release-preparation tasks into one runner and one VM report.

## What is combined

| Work | Deliverable |
| --- | --- |
| Managed source-worker mapping | Read-only systemctl metadata and reviewed supervisor hash comparison; no raw arguments or credentials exported |
| Closed release source staging | Guarded Source, worker call site, coordinator and guard generated from the reviewed originals |
| File change review | RELEASE-REVIEW.json with exact old/new file hashes and deployment prerequisites |
| Dependency review | Direct import resolution and origin fingerprints without executing package initializers |
| Bounded startup | Two separate CLI starts, each returning CLOSED twice and exiting without backend imports or databases |
| Managed-unit syntax | A separate bounded closed-probe unit verified using systemd-analyze when available; never installed or started |
| File rollback rehearsal | Disposable-directory swaps, interruption recovery, original mode/content restoration and removal of the newly created module |
| Integration | Optional previous 191 plus 16 new cases, expected 207 |

The file review lists three intended future installed targets: Source, worker and the new guard module. The staged coordinator is retained for candidate validation; the actual worker has no execution-session factory configured. The closed probe unit is NOT the production source-worker unit and is not evidence of a managed service start.

## VM commands

```bash
.venv/bin/python hilega-closed-release-v1/apply_and_test.py --repo "$PWD"
```

Expected targeted cases: 16. After success:

```bash
.venv/bin/python hilega-closed-release-v1/apply_and_test.py --repo "$PWD" --integration
```

Expected combined cases: 207. This remains candidate integration, not full repository regression. No behavioral tests were run in the assistant workspace; syntax checks only.

The runner requires the corrected hilega-exclusive-route-v1 folder and its successful combined 191-case report. It also requires the prior expanded coordinator, second-cycle V3, history-aware preparation and application-cycle-close folders. Exact hashes are checked before and after. Do not overwrite corrected folders with their original ZIPs.

A new hilega-closed-release-stage-* directory contains the staged sources, STAGED-MANIFEST.json, SERVICE-INVENTORY.json, RELEASE-REVIEW.json, DIRECT-DEPENDENCIES.json and the bounded probe unit. VM-VALIDATION.json is written in this package. A failed/unavailable service query or unit verification is reported explicitly; it does not count as service readiness. Passing behavioral tests does not override those inventory limitations.

## Why no live apply is included

File rehearsal accepts only explicitly marked disposable roots and rejects Git checkouts and symlink targets. It cannot apply the release to this application repository. Its backups are synthetic test files, not backups of the running application databases. Multi-file replacement is not one atomic operation: interruptions leave a durable APPLYING record that the rehearsal rollback can restore. Unexpected external edits block restoration before any target is overwritten.

The installed supervisor validates its existing runner/configuration approvals. Neither is rewritten here. Deployment still needs all old source processes quiesced, reconciled release/dependency/supervisor approvals, code and database backups, state/bridge-lease migration review, bounded actual service startup, cursor/heartbeat checks, and reviewed rollback/restart. No environment files or private supervisor configuration are opened by this package.

The direct-dependency report is a reviewed inventory, not a full transitive runtime lock or an approval to deploy. Unresolved names remain visible, and dependency_manifest_fully_reconciled stays false. This package does not provision production authority, configure a live execution factory, validate broker networking, complete fees/net P&L or release broker cash. No service control commands, live application database access or production enabling is included.
