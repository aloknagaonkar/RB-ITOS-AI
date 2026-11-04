# Signed disabled bootstrap handoff — combined VM candidate check

This package adds an explicit, signed, local-only handoff to the passed local-bootstrap v2 candidate. It has **no apply, resume, trust provisioning or live enrollment command**. Run it outside trading hours as well: all behavior checks use synthetic clocks, keys, signals and temporary databases.

One command stages a new candidate and runs 13 handoff checks under one disposable user systemd service. It checks current installed status before and after. The service is restricted to Unix sockets, and pytest also denies network connections. Two checks fork a handoff actor and SIGKILL it after durable commit boundaries, then recover with a fresh signed recovery approval. Four additional checks interrupt commit checkpoints.

The handoff preserves authority/pin/token bytes and the source cursor. Only the context and signed owner's lease binding may change. Unknown context changes, unsigned new leases, expired approvals, revoked issuers and capture-key approvals are rejected. The signed receipt has a read-only consumer; it is not an execution permission.

## Run on the VM

```bash
cd ~/RB-ITOS-AI
unzip hilega-bootstrap-handoff-v1.zip
.venv/bin/python hilega-bootstrap-handoff-v1/manage.py \
  --repo "$PWD" \
  --current-plan "$PWD/hilega-group2-upgrade-plan-6ol7neof/PLAN.json" \
  --current-plan-sha256 c57d04cfb8e2492f63c6eccff7ebcb43fa29c4cd99cca36c17f9425ed615d9b6 \
  --bootstrap-review "$PWD/hilega-local-bootstrap-review-fwn8tqx1"
```

Prerequisites: the existing VM venv with pytest, user systemd, the unchanged worker-qualification v1 / combined v2 / local-bootstrap v2 packages, the active plan above, and the passed bootstrap review. No package installation is performed.

Outputs go into a new private `hilega-bootstrap-handoff-review-*` directory: candidate, `TESTS.xml`, `MANAGED-PROCESS.json`, before/after status, `RESULT.json` and `MILESTONES.md`. A failing batch produces no success receipt. Inspect the reported JSON/XML; do not deploy a failed candidate.

## Scope and limits

This qualifies a **handoff actor under systemd**, not the full configured source-worker CLI. It does not wire factory dispatch, install automatic boot rebinding, test an actual VM reboot, or resolve broker time/fee evidence. Recovery is explicit and bounded to the signed target lease; a further source restart requires another review. SIGKILL checks cover named durable checkpoints, not every possible power-loss or filesystem failure. Existing context expiry is never extended.

The one-position policy is unchanged. Premium and daily-loss caps remain null. Live controller remains paused and the real order gate remains closed. No behavior tests were run on the development host; syntax and archive integrity checks only. VM results are required before marking this candidate qualified.
