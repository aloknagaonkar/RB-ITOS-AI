# Isolated allocation to simulator lifecycle integration

NO installation/apply, service restarts, production orders, real credentials or
active DB writes. This standalone controller uses the actual installed simulator
Service/SimBroker and a bundled copy of the offline reservation ledger. Tests/demo
must be run on your VM. Only Python AST syntax was checked in preparation.

Run from ~/RB-ITOS-AI:
PYTHONPATH=backend:. .venv/bin/python -m pytest -q hilega-production-allocation-simulator/test_controller.py
Then:
PYTHONPATH=backend:. .venv/bin/python -u hilega-production-allocation-simulator/demo.py --output data/research/hilega-allocation-simulator-demo-v1

The demo checks exact installed dependency hashes from the bridge-health milestone.
It writes isolated simulator, allocation DBs, summary.md and report.json under a
NEW output path. Cash100000/premium100/lot65/buffer100 are fixtures, not actual
funds, prices, NIFTY points or P&L. No market session is required.

Implementation:
- Persist signal/plan link; reserve before simulator Service.submit_entry.
- Controller lock serializes its submit/reconcile calls; installed Service retains
  its own authoritative control/Pause lock. Pause between reservation and service
  submission still blocks BUY. Verified no-intent/no-order rejection releases hold.
- Partial/full fills and pending exits retain full hold. Release requires Service
  reconciliation plus terminal entry/exit evidence, zero remaining and no cleanup.
- Unknown acceptance with unavailable evidence retains hold. If reconciliation
  later proves terminal zero-fill cancellation, release is allowed. Never resubmit.
- Crash between reserve/intent remains UNKNOWN with hold, requires review; it is
  not assumed rejected because no current order row was found after restart.
- Restart of controller reconstructs links and holds. Duplicate signal/plan never
  submits again; changed plans rejected. Signals rejected by Service are consumed,
  so later entry must use a new signal rather than replaying the rejected one.
- Reversal SELL may proceed while paused; pending SELL prevents opposite BUY via
  Service gate; reservation releases only once flat is verified. Test then uses a
  new eligible signal. Same-boundary queued reversal integration remains separate.
- Simulated fill notional beyond reservation causes Pause/review; no optimistic
  hold increase. Fee/slippage and actual broker evidence validation still pending.

IMPORTANT boundaries:
This is a controller used only by these isolated tests/demo. The running bridge,
watch CLI, UI and Service direct callers are NOT wired to it and can bypass this
controller if called directly. No claim that installed execution enforces this
allocation policy. Event-bridge central-gate wiring and full regression must follow
before application rollout. Demo process changes only its own opt-in environment
flag to0 and uses no health lease; existing health protections are not changed.

Initial integration supports exactly ONE instrument/lot-configured leg per signal,
as agreed for initial pilot. Multi-leg baskets explicitly reject before reserve
or order submission. The offline ledger already tests one-to-five-leg arithmetic,
but actual multi-leg orchestration, partial basket rollback and broker submission
need separate implementation before using 4/5 selected strikes.

Separate SQLite databases mean reserve + intent is a recoverable sequence, not
one cross-DB atomic transaction. Orphan reservations fail closed; no automatic
reclaim. Controller and Service locks are single-host, not distributed execution.
Ledger terminal/flat proof is derived ONLY from the simulated Service evidence;
it is not valid production broker ownership proof.

Conservative cap remains latest half-cash minus whole holds. Actual Upstox cash
already debited/reserved by broker must not be double-counted in production.
No live cash mapping, quote/contract validity, daily loss, real transport,
external exit attribution or production readiness is approved by these tests.
Keep actual Production workspace PAUSED/SIMULATION_ONLY. No apply step here.
