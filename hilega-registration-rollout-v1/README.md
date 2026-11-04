# Combined registration rollout, wrapper and pause recovery

One package prepares the exact closed installation plan for the passed 38-case external registration candidate, checks wrapper/recovery boundaries, and produces a clear live-activation gate packet. **Closed code deployment and live activation are separate outputs.** There is no activation, root-provisioning or controller-resume action in this tool.

## Prepare on the VM

```bash
cd ~/RB-ITOS-AI
unzip hilega-registration-rollout-v1.zip
.venv/bin/python hilega-registration-rollout-v1/manage.py \
  --repo "$PWD" \
  --current-plan "$PWD/hilega-group2-upgrade-plan-d_l5gg3t/PLAN.json" \
  --current-plan-sha256 86e185662e51e325abae7a24e06ea074f1a01afa0476e135c1fe19a5504dceac \
  --bindings-review "$PWD/hilega-registration-bindings-review-vwy1tm9d" \
  --trust-request-sha256 d0e5d2a32a9c86b975df6d224205ffed995c1210c1afa0982d76dad337243f11
```

Requires the earlier packages/review, current user systemd services, and existing venv. Installs no packages. The default check reads current state and creates private plan/rehearsal artifacts; it does not stop application services, replace installed files or modify live databases.

## Combined checks and outputs

- Verifies the passed candidate release, 38-case receipt/XML and exact unapproved trust review request. The 38 behavioral cases are not reexecuted here.
- Uses bootstrap-deploy v1 for current installed status before/after, matching the active wrapper/recovery plan.
- Runs eight negative checks on the exact new wrapper: both handoff pointer names and both factory attachment pointer names, each supplied via environment and dotenv. Each must reject activation before launching the worker.
- Runs native pause recovery against two disposable databases and managed default worker startup/restart against the new candidate.
- Binds immutable release destination, wrapper, recovery unit/configuration, observed service/configuration files, current controller version/session and rollback release to hashes.
- Creates a 30-minute `PLAN.json`, hash, `CHECK-VALIDATION.json`, `MILESTONES.md` and `ACTIVATION-GATES.json` in a new `hilega-group2-upgrade-plan-*` folder.

The gate packet lists live prerequisites without pretending they are resolved: independently approved issuer/private bindings; exact activation wrapper/supervisor/recovery approval; broker timestamp contract; final fees/ownership evidence; fresh real disabled seed, durable handoff and signed enrollment; final operational/gate-release review. This batch does not recapture broker evidence or turn unknown fields into approvals.

## After a passing check

Use the exact plan path and hash printed by the VM within its `apply_before` deadline:

```text
.venv/bin/python hilega-registration-rollout-v1/manage.py --repo "$PWD" --action apply --plan ABSOLUTE_PLAN_PATH --approve-plan-sha256 PRINTED_PLAN_SHA256
.venv/bin/python hilega-registration-rollout-v1/manage.py --repo "$PWD" --action status --plan ABSOLUTE_PLAN_PATH --approve-plan-sha256 PRINTED_PLAN_SHA256
.venv/bin/python hilega-registration-rollout-v1/manage.py --repo "$PWD" --action rollback --plan ABSOLUTE_PLAN_PATH --approve-plan-sha256 PRINTED_PLAN_SHA256
```

Apply reuses the verified transaction engine: checks exact inputs and paused/empty baseline, stops six services, rejects unmanaged processes, makes verified quiescent code/configuration and SQLite backups, installs a read-only release, swaps wrapper/recovery bindings, verifies pause recovery and starts services. Failures leave services stopped for explicit rollback. Rollback refuses unknown external file edits and restores verified prior file bindings. Databases are never automatically restored and source cursors are never rewound.

Real backups are made **during apply**, not during this check. New immutable bundles/configs are retained for audit. Actual VM reboot and an actual rollback cycle for this new release are not certified by check.

## Closed deployment boundary

The installed wrapper rejects all four activation pointer names in inherited environment and the selected dotenv file. It installs none of them. Factory registration stays disabled, the controller paused and the unconditional order gate unchanged. No real trust key/context/mailbox/attachment is provisioned. Capacity stays one; premium and daily-loss caps remain null.

Real activation needs a future exact activation/recovery plan and the missing evidence; this package does not generate a runnable live activation command. Group 2 remains incomplete after a closed install.

No behavior tests ran on the development host. Local checks are syntax/AST, generated wrapper syntax, byte/AST comparison of the reused transaction engine and ZIP integrity. VM receipts decide qualification.
