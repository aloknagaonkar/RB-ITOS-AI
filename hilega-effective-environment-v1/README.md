# Effective environment and proposed closed-release contract

Current milestone: 212 candidate integration cases passed; read-only inspection found a paused controller, no pending stop, no active preparation in inspected tables, and an empty LIVE_CLOSED adapter. The adapter path was selected from a default, so the next check must establish the intended path from the approved startup contract.

This package combines environment-hash verification, effective database path selection under load_dotenv(override=False), a repeat read-only database baseline, and a proposed release file contract. It writes no approvals and performs no deployment.

## Run on VM

Keep all corrected previous folders and reports, including hilega-readonly-readiness-v1 (14 or 226-case pass) and hilega-closed-release-v2 (212-case combined pass). The verified V2 stage must remain available.

```bash
.venv/bin/python hilega-effective-environment-v1/apply_and_test.py --repo "$PWD"
```

Expected: eight synthetic tool tests. The actual inspection results are separate booleans; passing tests does not make a blocked environment review successful.

Optional combined candidate integration, expected 234 cases:

```bash
.venv/bin/python hilega-effective-environment-v1/apply_and_test.py --repo "$PWD" --integration
```

No behavioral tests were run in the assistant workspace. Syntax checks only. The previous 212-case evidence is retained; rerunning the full combined suite is optional for this read-only inspection change.

## How path selection is established

The exact reviewed supervisor and existing approval hashes are checked again. Its captured source-worker argv must match the reviewed closed command. The worker's chosen env file must be the repository .env covered by the supervisor's env_sha256. That hash is checked before parsing. Only two database setting names are selected: captured environment takes precedence, then the pinned env file, then the reviewed Source default.

Relevant interpolated or empty settings, duplicate --env-file arguments, uncovered env files, symlink paths, changed configuration and identical application/adapter paths block confirmation. dotenv interpolation is disabled for review; unresolved references are not expanded using the review shell. No credential values or raw config/env content are exported.

This confirms the startup contract on disk, not the actual running process's post-startup environment. It does not read /proc environment or claim process-level proof. A final quiesced startup/deployment check is still required.

## Outputs

The report points to EFFECTIVE-ENVIRONMENT.json, CONFIRMED-PATH-BASELINE.json and PROPOSED-RELEASE-CONTRACT.json. The proposed contract lists current and proposed hashes for the three intended installed files. It is explicitly REVIEW_ONLY_NOT_APPROVED. Real backups, worker quiescence, new release approval and deployment have not occurred.

Database reads use the previous query-only snapshot tool. No raw account/order rows are exported. Independent snapshots are not cross-database atomic and do not authenticate broker ownership or cash. Existing lifecycle/state findings remain review blockers, never automatically adopted or deleted.

No service control, production factory configuration, broker network access, approval rewriting, installed source replacement or live execution enabling is included. Full transitive/external dependency reconciliation, broker policies, fees/cash handling and full release regression remain pending.
