# Bounded recovery of the approved closed-hook startup

The first managed start was stopped within the same second because the rollout tool tested an old heartbeat immediately. All six services were then confirmed inactive. This package leaves the original rollout files and approved PLAN.json unchanged and supplies a bounded health callback to the existing startup routine.

The log excerpt lacks timestamps and does not prove the new code initialized. Recovery therefore requires actual current evidence: a new bridge lease, no worker health error, controller PAUSED, active managed services, and two distinct advancing heartbeats on the same new lease. Old/frozen heartbeats, exited services, new ERROR/STOPPED states and controller changes cannot pass. Heartbeat polling has a 60-second wait window; systemctl operations have their separate existing timeouts.

## VM command

Keep the original rollout package, transaction, backups and approved plan intact. Run from the repository:

```bash
.venv/bin/python hilega-startup-retry-v1/startup_retry.py --repo "$PWD" \
  --plan "$PWD/hilega-closed-rollout-plan-qz5zlrk2/PLAN.json" --retry
```

This validates exact approved plan SHA, original rollout/tool manifests, installed code hashes, current approved configuration/environment pins, database paths, stopped service states and empty paused/closed baseline. It runs six synthetic wait/rejection tests before attempting startup. Omitting --retry performs these checks/tests only.

The stopped failure phase is explicitly recorded in STARTUP-RETRY.json before being transitioned back to the verified installed/stopped phase. The original startup routine restores only previously active units. The retry uses its failure cleanup, which attempts to stop any restarted services when verification fails. A failure must be inspected; no automatic rollback, reinstall, data rewind or repeated restart loop occurs.

Success: CLOSED_HOOK_RUNNING plus new_lease_verified and heartbeat_advanced. This means the closed preparation hook is running, not automatic broker buying/selling. No controller Resume or execution-authority provisioning is included. The original code/database backups are retained.

No behavioral tests ran in the assistant workspace; syntax checks only. Actual services are changed only by the explicit --retry command within the already approved startup scope.
