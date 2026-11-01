# Post-deployment checkpoint: closed preparation hook

The VM reported CLOSED_HOOK_RUNNING with a new lease, advancing heartbeat and paused controller. This read-only checkpoint verifies continued health over two snapshots six seconds apart, six active/stable service PIDs, exact installed hook hashes and the repaired companion integrity chain.

Run on VM:

```bash
.venv/bin/python hilega-postdeploy-check-v1/check.py --repo "$PWD" \
  --plan "$PWD/hilega-closed-rollout-plan-qz5zlrk2/PLAN.json" \
  --compatibility-review "$PWD/hilega-reference-compatibility-2jkluc07"
```

Expected: CLOSED_POSTDEPLOY_CHECK_PASS. A failed check records evidence for review; it never stops/restarts services, clears state or retries automatically. POST-DEPLOYMENT.json is saved beside the approved plan and backups. No new behavioral test suite is added for this read-only inspection; only syntax checks were performed in the assistant workspace.

The script imports the exact compatibility-reviewed companion under a non-main name and calls check_package only. It never runs account capture or lifecycle writes. SQLite is query-only; no raw account rows, configuration, credentials or account scope are exported. Independent database snapshots are not cross-database atomic. The reported heartbeat lease is compared internally and not exported.

Success certifies only this bounded post-deployment observation. It does not establish live execution readiness, account/broker reconciliation, execution-session integration, trading policy approval, fee/cash completeness, full release regression or ongoing future uptime. The controller stays PAUSED and production execution remains disabled.
