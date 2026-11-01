# Combined read-only readiness baseline

Previous checkpoint: 212 VM integration cases passed with zero unresolved direct imports. This package combines the next investigations. It does not deploy, enroll ownership, change approvals, pause/resume, stop/start a service or enable trading.

## Work combined

| Area | Evidence collected |
| --- | --- |
| Transitive local dependencies | Bounded static Python import graph with local-file hashes, optional imports, unresolved imports and dynamic-loader warnings |
| Installed dependency manifest | Existing preparation dependencies.json checked against its referenced files |
| Supervisor approvals | Exact reviewed runner fingerprint, recognized approval expressions, current runner/config hashes and captured closed-route command/environment checks |
| Actual local databases | Query-only SQLite snapshots of restricted control fields, cursor presence/sequence, table counts, adapter mode and ownership-state presence |
| Migration readiness | Existing preparation or owner/coordinator tables flagged for review; no automatic adoption, signature claim or migration |

Supervisor private configuration is read to verify the existing contract and locate captured database settings. It may contain credentials; none are printed, copied or written to reports. Only allowlisted database path settings remain in memory. The .env file is not opened. Existing approval bindings matching does not approve this new release, and the supervisor's environment hash is not revalidated here.

Database captures export no raw account/order/trade rows, account scope or journal path. Scope is fingerprinted. Each database has an independent read transaction; this is not a cross-database atomic or broker reconciliation proof. Concurrent running services may change their own databases independently. This tool issues no SQL writes. Signed ownership is not authenticated because no account signing key is loaded.

## VM usage

Keep the previous successful folders and reports, including hilega-closed-release-v2/VM-VALIDATION.json with the combined 212-case pass. The already verified V2 staged files must still exist at the reported stage path.

Run the combined investigation and 14 synthetic tool tests:

```bash
.venv/bin/python hilega-readonly-readiness-v1/apply_and_test.py --repo "$PWD"
```

The default includes the read-only actual database snapshot. It locates paths from captured supervisor settings where available. A fallback path is explicitly marked unconfirmed because .env is not loaded. To provide verified existing paths, use --application-db /absolute/path and --adapter-db /absolute/path. To omit actual database reads, add --skip-database-baseline; the report will retain that blocker.

Optional combined integration, expected 226 overlapping candidate cases:

```bash
.venv/bin/python hilega-readonly-readiness-v1/apply_and_test.py --repo "$PWD" --integration
```

Behavioral tests run only on the VM. Only syntax checks were performed in the assistant workspace. The synthetic tests validate the inspection tools; passing them does not imply that the captured real baseline is clear for deployment.

## Results and limits

The report points to a new hilega-readonly-readiness-* folder with SUPERVISOR-REVIEW.json, DATABASE-BASELINE.json, TRANSITIVE-LOCAL-DEPENDENCIES.json and INSTALLED-DEPENDENCY-PINS.json. VM-VALIDATION.json contains the combined status and blockers. Missing/changed supervisor contracts, unavailable databases, unconfirmed paths and existing ownership state remain explicit.

The local import graph is bounded at 250 modules and covers static imports, including optional/conditional imports. Dynamic loading requires separate manifest review. External distributions are not locked. The tool does not claim a complete production dependency closure even when every discovered import resolves.

Still required: new release/environment approval reconciliation, authenticated ownership and broker baseline, old-worker quiescence, real code/database backups, actual managed closed startup/rollback, execution factory and trusted authority, broker/policy validation, fees/cash handling and full release regression. Production readiness remains false.
