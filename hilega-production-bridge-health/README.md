# Simulator bridge heartbeat, watchdog and recovery

Production execution remains disabled. The optional strategy journal reader is
still OFF by default. This package does not start a reader, arm trading, change
.env, modify strategy rules or introduce any real broker transport.

## Implemented

- One kernel lifetime lock prevents two journal workers running against the same
  simulator DB. A second worker fails before it can pause/replace the first.
- A durable worker instance lease is recorded in the simulator DB. Heartbeats
  from a replaced instance cannot overwrite the new instance. Only the active
  lease holder may submit bridge entries when health is required.
- Heartbeat freshness is enforced inside Service.submit_entry under the same
  submission/control lock as Pause. There is no reliance on a browser poll.
- Resume also checks required health, so stale source/process state cannot be
  cleared merely by clicking Resume or Reconcile.
- Heartbeat limit: 15 seconds. The independent backend watchdog checks every
  5 seconds. Entries are blocked once heartbeat age exceeds 15 seconds; durable
  Pause follows on a healthy watchdog's next tick (normally within 5 more seconds).
- Source freshness limit: 390 seconds, with a same-IST-session check. This allows
  completed 5m observations plus operational delay; it is a health threshold,
  not a new indicator/entry/exit strategy rule. Only PROCESSED current-policy
  decision, price-observation and cutoff records refresh it. Reconstructed and
  error records do not turn an old source into a healthy one.
- Lost heartbeat/source health while ARMED durably pauses entries and reconciles
  pending simulator BUYs. A partial fill during cancellation follows the existing
  simulator cancellation/flatten policy. Established positions remain managed;
  health loss does not add a new strategy exit or automatically flatten them.
- Manual exits remain available while the bridge is unhealthy. Existing strategy
  exits still use their current rules. A stale bridge cannot permit reversal BUY.
- Heartbeat recovery never arms trading. A fresh explicit operator Resume and
  next eligible signal are required. Pending old entries cannot bypass a control
  version change or the existing 60-second entry age limit.
- Graceful stop immediately marks STOPPED and pauses. Forced kill releases the
  kernel lock; stale-heartbeat gating/watchdog protect subsequent entry attempts.
- A new session stays unarmed. The lease is session-bound: restart/reclaim the
  worker for the new trading session, verify source health, then explicitly resume.
- Missing/corrupt health evidence fails closed when health is required. Once a
  worker has claimed the DB, removing an environment flag does NOT erase that
  requirement. No automatic lease-clear/auto-resume control exists.
- Current simulator health, heartbeat/source age, process PID and short instance
  identifier appear in Upstox Production. The full instance submission token is
  not returned by the status API. Lifecycle transitions are audited.
- UI polling displays server health; it does not decide trading permission. A
  disconnected display stays stale even if the last reported heartbeat was healthy.

## Scope and limits

The heartbeat protects the SIMULATOR bridge, not actual Upstox orders. Broker
account/quotes/real fills, production execution, allocation reservation, loss
limits and full production readiness are still separate pending work.

PID is diagnostic; liveness authorization uses a lease and freshness, not PID
existence (which can be reused). The lock/control DB model is single-host, not a
multi-host distributed execution system. All backend processes must use the same
simulator DB path. Production should never be enabled by copying this design
without the remaining broker execution/risk validations.

The watchdog runs in the API backend. If the API is down, the entry gate still
checks freshness in the bridge process; when both are stopped, no bridge process
can place even simulated entries. Restart still pauses. This is not a full API,
network, disk, token, market feed and broker monitoring suite.

## Stage and validate on your VM

Keep the optional reader disabled and the Production workspace PAUSED.
Upload/extract into ~/RB-ITOS-AI:

```bash
cd ~/RB-ITOS-AI
set +e
unzip -n hilega-production-bridge-health.zip
.venv/bin/python hilega-production-bridge-health/install.py \
  --stage data/research/hilega-bridge-health-stage
.venv/bin/python hilega-production-bridge-health/validate.py \
  --stage data/research/hilega-bridge-health-stage \
  --output data/research/hilega-bridge-health-validation.json
```

Validation runs the new health/gate/API-watchdog tests, the previous bridge,
account, ownership, controls, observation and strategy regressions, two isolated
synthetic demonstrations and the staged frontend build. No network broker calls
or active app DB writes occur in validation. Tests/bridge flags are isolated.

Only Python AST syntax was checked in the preparation environment. No project
tests, demos, replay or frontend build were run locally. Your VM must PASS all
validation steps before apply.

The installer checks exact hashes of the known prior core/bridge/CLI/workspace/
frontend files and validated observer/ownership dependencies. It refuses a
changed source rather than overwriting it. Do not bypass its guard.

## Apply after PASS

Make sure the optional reader is stopped and HILEGA_PRODUCTION_SIM_BRIDGE_ENABLED
is absent or 0 in .env and the shell. The installer refuses apply when that flag
is 1. This avoids updating an already-running pre-heartbeat reader.

```bash
.venv/bin/python hilega-production-bridge-health/install.py --apply \
  --validation data/research/hilega-bridge-health-validation.json
```

After APPLIED, rebuild UI and restart ONLY the UI/API:

```bash
if npm --prefix frontend run build; then
  bash scripts/restart_hilega_ui_api_safe.sh
fi
```

The restart re-pauses simulation controls and preserves the strategy worker.
It does NOT start the journal reader or enable production. Existing simulator
positions/ledger are not reset. Schema additions are additive. Backups include
changed source; rollback must not restore an older trading DB over new evidence.

Open Upstox Production with your existing workspace control key. With no reader
enabled or claimed, the health panel should show NOT_ENABLED. If a worker was
previously claimed and stopped, expect STOPPED/required; do not erase health
records to force an ARMED label.

## Save the isolated health demonstration

```bash
PYTHONPATH=backend:. .venv/bin/python scripts/hilega_production_bridge_health_demo.py \
  --output data/research/hilega-bridge-health-demo-v1
```

Use a fresh output directory. Synthetic reports show startup paused, healthy but
still paused, explicit Resume, simulated entry, lost heartbeat/automatic Pause,
recovery without auto-resume, manual exit, next fresh signal and stopped-worker
entry blocking. No actual broker requests, prices, orders or performance claims.

## Status via the same authenticated CLI

```bash
.venv/bin/python scripts/hilega_production_control.py \
  --token-file ~/hilega-private/production-workspace.token status \
  | .venv/bin/python -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({k:d.get(k) for k in ["label","control","bridge_health"]},indent=2))'
```

Keep control keys, account pins, tokens and snapshots private and outside Git.

## Later optional journal-reader validation

Do not enable it merely because this package installs. After validation and a
separate deliberate simulation session: set the opt-in flag to 1, safely restart
API so its initial NOT_STARTED gate is active, then start the existing --watch
reader. Startup pauses, acquires the lifetime lock, baselines existing journal
history and reports STARTING/SOURCE_NOT_READY until it has verified fresh source
and reconciled simulator ownership. Only then may the operator resume through
UI/CLI for a new signal. No automatic arm occurs.

--synthetic-fills remains an explicit fake-fill option. Without it simulator BUYs
remain pending. Neither mode uses Upstox execution or current option premiums.
A new source signal on recovery can be blocked while health catches up; it is not
replayed later. Review state and resume for a fresh signal.

This package adds no cron, supervisor auto-restart or production startup action.
Unattended operation, broker reconciliation, quote/risk checks and controlled
production pilot remain pending. Keep production execution disabled.
