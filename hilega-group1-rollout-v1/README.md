# Group 1 — exact closed bundle rollout

Preparation is read-only for installed sources and application services. It creates an exact plan, staged wrapper and test report. Mutations are separate actions requiring the prepared plan SHA256.

First run the quick ten-case maintenance checks:

    .venv/bin/python hilega-group1-rollout-v1/manage.py --repo "$PWD" --candidate-review "$PWD/hilega-group1-review-13x5psb_"

Then run the closed-release integration checkpoint once:

    .venv/bin/python hilega-group1-rollout-v1/manage.py --repo "$PWD" --candidate-review "$PWD/hilega-group1-review-13x5psb_" --integration

Integration reruns the prior Group 1 combined selection (304 cases), compares all tested artifact file hashes to the artifact that passed managed rehearsal, then runs ten maintenance tests: 314 total. This is regression for the closed source-worker change scope, not a claim that every repository/API/service test passed. No behavioral tests are run in the packaging workspace. A targeted-only plan cannot be applied.

The proposed change installs the exact bundle at data/runtime/hilega-closed-releases/<manifest-sha256> and replaces only scripts/hilega_production_simulator_bridge.py with a hash-verifying wrapper. The supervisor command/configuration and companion sources stay unchanged and their hashes are bound to the plan. The wrapper verifies every bundle file and installed Python/native runtime payload before launching the closed registered worker. The runtime policy import change is the previously verified unchanged RSI exception extraction; no installed policy file is modified.

All six listed application units are stopped during apply. Kernel/process quiescence and an empty paused closed baseline are required. SQLite backup() creates real application/adapter backups with quick_check validation, and the original worker bytes are retained before any replacement. No database is ever automatically restored. API/worker PID records must be ready before source startup. Startup requires a new lease on the current source PID and two advancing healthy heartbeats while control remains paused and lifecycle tables stay empty.

After inspecting the concrete PLAN.json and CHECK-VALIDATION.json, actions use:

    .venv/bin/python hilega-group1-rollout-v1/manage.py --repo "$PWD" --action ACTION --plan /absolute/PLAN.json --approve-plan-sha256 EXACT_REPORTED_DIGEST

Actions:
- apply: stop services, check quiescence, create real backups, install immutable bundle and replace worker; leave services stopped.
- start: restore previously active services, wait for PID inventory, start source and verify closed health. A failure stops the started set and retains evidence.
- status: read-only bounded health and exact hash validation for the deployed/restored worker.
- hold: stop the managed application set for controlled recovery.
- rollback: while services are stopped, restore verified old worker bytes only; retain bundles and DB backups. Then start restores the old closed worker. Unknown external edits block rollback.

Never bypass a hash, mode, nonempty-lifecycle or PID check. Keep the old rollout plan, old review folders and new real backups. There is no owner enrollment, source Resume, execution authority provisioning or live-gate change. Closed installation does not certify broker behavior, full application dependencies, fees, cash release, positive execution registration or production readiness. Live BUY/SELL remains disabled.
