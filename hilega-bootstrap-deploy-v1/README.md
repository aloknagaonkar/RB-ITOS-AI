# Closed integrated bootstrap/worker deployment

This package turns the passed 36-case worker candidate into an exact, time-bounded installation plan. The default `check` action does not change application services, code, configuration or databases.

It verifies the candidate/proposal/current release; runs two new-wrapper activation rejection checks, two native recovery scenarios and managed default worker startup/restart; and binds the launcher wrapper, recovery service, recovery payload, source release and rollback release to exact hashes. The earlier 36 cases are verified from their receipt and XML, not reexecuted.

## Prepare the plan on the VM

```bash
cd ~/RB-ITOS-AI
unzip hilega-bootstrap-deploy-v1.zip
.venv/bin/python hilega-bootstrap-deploy-v1/manage.py \
  --repo "$PWD" \
  --current-plan "$PWD/hilega-group2-upgrade-plan-6ol7neof/PLAN.json" \
  --current-plan-sha256 c57d04cfb8e2492f63c6eccff7ebcb43fa29c4cd99cca36c17f9425ed615d9b6 \
  --worker-review "$PWD/hilega-bootstrap-worker-review-bk5l7chh" \
  --proposal-sha256 f1aa4e6add58a2770a7b218245e7413519d37fdf95c9a3db023ed22067165748
```

Needs the unchanged earlier VM packages and passed review, current user systemd services and the existing venv. No installations or broker requests are made. Disposable native tests write only new temporary databases; managed rehearsal uses a disposable unit.

A successful check prints `PLAN.json`, its exact SHA256 and a 30-minute `apply_before`. It creates `MILESTONES.md` and `CHECK-VALIDATION.json` beside the plan. No real backups exist until apply quiesces the six application services.

## Apply/status/rollback interface

After reviewing the generated exact plan, use its printed folder and SHA256:

```text
.venv/bin/python hilega-bootstrap-deploy-v1/manage.py --repo "$PWD" --action apply --plan ABSOLUTE_PLAN_PATH --approve-plan-sha256 EXACT_PRINTED_SHA256
.venv/bin/python hilega-bootstrap-deploy-v1/manage.py --repo "$PWD" --action status --plan ABSOLUTE_PLAN_PATH --approve-plan-sha256 EXACT_PRINTED_SHA256
.venv/bin/python hilega-bootstrap-deploy-v1/manage.py --repo "$PWD" --action rollback --plan ABSOLUTE_PLAN_PATH --approve-plan-sha256 EXACT_PRINTED_SHA256
```

Apply verifies unchanged inputs and paused/empty state, stops the six services, rejects unmanaged processes, makes verified code/configuration and SQLite backups, installs an immutable release, replaces wrapper/recovery bindings, verifies native pause recovery, and starts services with a healthy new lease. An interrupted apply leaves services stopped for explicit rollback. Rollback refuses unexpected external file edits and restores verified prior wrapper/service bindings. It does **not automatically restore databases or rewind source cursors**. Retained bundles/backups remain for audit.

## Activation boundary

Only code is installed. No private trust root, context, signed mailbox or handoff environment settings are installed. The new wrapper rejects `HILEGA_DISABLED_HANDOFF_CONFIG` and its SHA256 setting in both inherited environment and the selected dotenv file; a later activation needs a separately reviewed wrapper/configuration. Factory registration remains disabled, controller paused and hard order gate unchanged. One position; premium/daily-loss limits remain null.

Recovery still performs native pause only. It does not provision authority, silently rebind leases or activate a factory. Actual VM reboot and this release's real rollback cycle are not certified by the check. Broker time/fee/ownership evidence, real trust and fresh enrollment, execution-factory qualification and final readiness remain separate unfinished milestones.

Behavior tests are VM-only. Development-host checks are syntax/AST, transaction-engine source comparison and ZIP integrity only.
