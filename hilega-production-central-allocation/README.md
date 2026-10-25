# Central simulator allocation gate and UI/CLI visibility

Staged promotion only; no production broker transport, real cash coupling,
strategy rules or Sandbox worker changes. Source preparation ran only Python
AST syntax checks. Tests, demonstrations and UI build MUST run on your VM.

## What changes
- Workspace Service enrolls its DB when SIMULATION_ONLY is configured. Enrollment
  persists: later removing that environment value cannot bypass the BUY gate.
- Public Service.submit_entry validates Pause, health, signal freshness and
  exposure, then commits the allocation hold under the SAME control lock before
  _submit persists intent and calls simulator BUY transport.
- Direct public submissions and journal Bridge entries/reversals share that gate.
- Synthetic cash must be explicitly supplied; missing/stale cash blocks Resume
  and new BUYs. No default funds are invented. Snapshot freshness limit30 seconds.
- Whole initial single-leg cost = price * quantity + provisional buffer100.
  Cap50% synthetic cash, round cost up and cap down. No lot inflation to spend cap.
- Order pending, partial entry, established position and pending exits retain
  full hold. Service order/position reconciliation must prove terminal flat
  before release. Exits/Pause do not require fresh allocation cash.
- An orphan hold after crash before intent does not auto-release; it blocks
  reconciliation/new entries for review. Unknown order outcomes retain hold until
  Service reconciliation resolves acceptance and terminal position evidence.
- Existing fully closed historical simulator intents may remain in DB without
  new holds; unreserved active/pending/exposed entries require review.
- UI and authenticated existing control CLI status expose allocation status,
  synthetic cash/cap/held/remaining and snapshot age. Start disabled if unready.
  Real Upstox account cash panel remains separate and read-only.
- Optional journal CLI --synthetic-cash VALUE refreshes explicit fictional funds
  each poll. No flag means no new synthetic funding. It never arms trading.

## Scope
Single instrument per signal only; existing source dispatcher/Service handles
one CE/PE at a time. Multi-strike production baskets remain unsupported.
Legacy standalone unit fixtures with mode DISABLED and no enrolled DB remain
unfunded/unenrolled test helpers. They are not reachable through disabled workspace
API and are not evidence of production permission. Enrolled DB cannot opt out.

Holds and BUY intents use the same simulator DB but separate durable commits.
Crash between them conservatively leaves an orphan requiring review. Not a
cross-process distributed broker transaction. All active processes must use the
same DB path and validated code; stop the old reader before applying.

Only simulator-owned order/position data is trusted here. External real Upstox
activity, production fills, charges/slippage, market contract mapping and loss
limits are not covered. Cash is synthetic; real broker cash may already exclude
premium/margin. Real funds debit/reservation mapping to avoid double counting is
STILL PENDING. Do not replace fictional cash with real balances and call it live
risk enforcement. No production activation or risk approval in this package.

## Stage and validate
Keep workspace PAUSED and journal reader stopped/opt-in flag absent or0.

cd ~/RB-ITOS-AI
set +e
unzip -n hilega-production-central-allocation.zip
.venv/bin/python hilega-production-central-allocation/install.py \
  --stage data/research/hilega-central-allocation-stage
.venv/bin/python hilega-production-central-allocation/validate.py \
  --stage data/research/hilega-central-allocation-stage \
  --output data/research/hilega-central-allocation-validation.json

Validator runs new central gate tests plus previous health/bridge/account/ownership/
controls/workspace/strategy regression, three synthetic demonstrations and staged
frontend build. It does not start active services, read credentials or call broker.

## Apply only after PASS
Installer checks package/target hashes and validation proof. Refuses when reader
opt-in is1 or simulator has pending/uncertain orders or any remaining position.
Do not bypass guards or reset a DB to make it pass. Investigate existing evidence.

.venv/bin/python hilega-production-central-allocation/install.py --apply \
  --validation data/research/hilega-central-allocation-validation.json
if npm --prefix frontend run build; then
  bash scripts/restart_hilega_ui_api_safe.sh
fi

Restart only API/UI. Source additive schema; source backup produced. No DB rollback,
reset, auto-arm or worker start. After restart PAUSED and synthetic funds not
configured is expected. Strategy worker PID must remain unchanged.

Existing authenticated CLI status now includes allocation:
.venv/bin/python scripts/hilega_production_control.py \
 --token-file ~/hilega-private/production-workspace.token status

Optional explicit fictional cash update (does not Resume):
PYTHONPATH=backend:. .venv/bin/python scripts/hilega_sim_allocation.py \
 --cash 100000 --confirm-synthetic-cash

Snapshot expires30 seconds; do not keep manually refreshing for unattended use.
Later deliberate simulator reader sessions can use --synthetic-cash 100000 with
existing --watch --synthetic-fills; keep reader OFF until separate test instruction.
No automatic cash refresh in the API and no account balance imported into gate.

Private synthetic demo, only after install:
PYTHONPATH=backend:. .venv/bin/python scripts/hilega_central_allocation_demo.py \
 --output data/research/hilega-central-allocation-demo-v1

Prior standalone research runners pin exact installed hashes and may correctly
block after this promotion. Do not edit their old manifests to fake parity;
this package's staged checks target the new source revision.
