# Registered execution-factory Bridge/process qualification

This VM-only candidate fixes the registered factory's attachment boundary: the outer worker supplies a `Bridge`, while the private loader/coordinator requires a guarded preparation `Source`. The adapter creates one stable Source wrapper only after `require_live_clearance`, reopens existing preparation state, and rejects changed bridge identity, journal or lease. Missing preparation/owner tables are rejected before constructing Source; no implicit bootstrap is performed.

The installed default remains closed. This check stages candidate code; it does not deploy it or activate registration.

## Run

```bash
cd ~/RB-ITOS-AI
unzip hilega-factory-process-v1.zip
.venv/bin/python hilega-factory-process-v1/manage.py \
  --repo "$PWD" \
  --current-plan "$PWD/hilega-group2-upgrade-plan-d_l5gg3t/PLAN.json" \
  --current-plan-sha256 86e185662e51e325abae7a24e06ea074f1a01afa0476e135c1fe19a5504dceac
```

Requires the unchanged prior packages, the applied bootstrap deployment plan, pytest in the existing VM venv and user systemd. The current status is checked using **bootstrap-deploy v1**, the tool bound to the current wrapper/recovery installation.

## Combined validation

One disposable managed unit runs 30 checks:

- 5 new Bridge checks: two full candidate cycles in a forked child, actual gate before adaptation, changed lease, changed Bridge identity and absent preparation/owner schema.
- 16 existing private-file/registration tests.
- 8 existing heartbeat/lease tests.
- 1 seed preflight.

The positive synthetic child uses the actual registered worker, pinned synthetic grant/registry, private loader, factory and coordinator. Four sends are intercepted; socket connections are denied in Python and the systemd unit permits only Unix address families. Gate overrides exist only in test memory; the child verifies two completed cycles and the parent checks its real gate is still closed. Other existing positive tests likewise use explicit in-memory overrides. This is not permission to submit orders.

The release source gate, disabled factory registration and one-position policy bytes are unchanged. No broker token from the live installation is loaded for tests; keys, tokens, databases and activity are synthetic.

## Output and limits

Creates `hilega-factory-process-review-*` with candidate, `TESTS.xml`, `MANAGED-PROCESS.json`, before/after live status, `RESULT.json` and updated `MILESTONES.md`. The candidate succeeds only if all 30 cases pass without skips/errors/failures.

This qualifies the registered-factory Bridge boundary in a managed synthetic process. It **does not execute the positive factory branch through the complete outer source-worker CLI**; that startup/recovery integration is still separately identified in the report. The prior exact CLI handoff check qualified the closed handoff path. No live apply plan, root provisioning, real enrollment, production transport or real market readiness is included here. Broker timestamp and fee evidence remain unresolved.

No behavioral tests ran on the development host. Syntax, exact gate-placement source anchors and ZIP integrity were checked only; VM results decide qualification.
