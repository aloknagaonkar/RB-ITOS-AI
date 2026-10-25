# Offline allocation reservation foundation

No install/apply step, credentials, network/broker requests, app DB writes,
strategy changes or production execution. The standalone module and demo use
explicit OFFLINE_FIXTURE inputs and a NEW isolated SQLite database.

This milestone is NOT WIRED to the simulator bridge or live execution path.
Passing it does not mean the running application enforces allocation limits.
Integration, real funds/order reconciliation and production risk approval remain
separate work. Tests must run on your VM; only Python AST syntax was checked
while preparing the package. No tests or demonstration were run locally.

## Rules under test
- One account per DB, one-to-five unique configured strikes (-2 through +2).
- One directional CE OR PE basket. Both directions cannot share one reservation.
- Positive ask, broker lot size and configured lot count; quantity must match.
- Per-leg ask * quantity + explicit charge/slippage buffer, rounded UP to cents.
- Cap is 50% available cash, rounded DOWN; never a target to spend automatically.
- BEGIN IMMEDIATE transaction serializes funds updates, reservation creation and
  release. Basket is all-or-nothing, not separate per-leg approvals.
- Sum of outstanding holds plus new basket must fit latest cap.
- Freshest registered funds snapshot, same IST session, maximum age30 seconds.
- Same reservation ID/plan is idempotent. Same ID changed plan is rejected.
  Same session/signal cannot reserve again under a different ID, even after release.
- RESERVED, SUBMITTED, PARTIAL, FILLED and UNKNOWN retain full original hold.
  Filled entry still represents exposure; entry fill is NOT permission to release.
- UNKNOWN prevents new reservations until explicit offline reconciliation evidence.
- RELEASED requires explicit aggregate terminal/no-exposure fixture confirmation.
  Partial cancel does not release while filled quantity, pending orders or exits
  remain. No timer/session rollover releases holds automatically.
- State/time regression, evidence ID conflict and account changes are rejected.
- Restart preserves holds. Existing holds survive a lower later cash snapshot;
  new reservations then block. Database audit events record state changes.

## Important scope boundaries
The evidence API accepts trusted OFFLINE fixture declarations, including a
terminal_no_exposure boolean. It does NOT validate broker order IDs, actual
remaining quantities, fill attribution or signatures. Never feed arbitrary live
rows into it or treat the boolean as sufficient production proof. Quantity-level
broker reconciliation must establish that evidence before production integration.

The ledger does not decide quote freshness, contract expiry, freeze limits,
controls/Pause, strategy event age, signal authenticity, existing exposure,
daily loss or order permissions. Prior validators cover some of those separately;
all must be joined atomically at the eventual submission gate.

Latest available cash may ALREADY exclude broker-held premium/margin. This offline
version conservatively subtracts full local holds from half of that latest cash.
It can double-count broker debits and block affordable baskets. No attempt is made
to add broker margin back or infer replenishment. Correct live cash/reservation
mapping, acknowledgement transitions and exposure valuation are pending and must
be resolved before integration. This milestone validates conservative serialization
and persistence, not production capital utilization.

Whole basket holds stay until the complete basket is reconciled flat; no partial
release optimization. Upward execution price/slippage beyond the buffer, fees,
quote movement and unowned account exposure remain production blockers. There is
no broker-calculated margin/charges estimate, daily-loss limit or risk approval.

## VM commands

cd ~/RB-ITOS-AI
set +e
unzip -n hilega-production-allocation-reservations.zip
.venv/bin/python -m pytest -q hilega-production-allocation-reservations/test_ledger.py

After tests pass:
.venv/bin/python -u hilega-production-allocation-reservations/demo.py \
  --output data/research/hilega-allocation-reservations-demo-v1

Output: summary.md, report.json, isolated allocation.sqlite. Synthetic demo uses
INR100,000 cash, INR50,000 cap, five legs of 65 units at premium100 plus buffer100
per leg: basket INR33,000; second INR33,000 basket blocked. Unknown/partial/full
fill retain INR33,000; explicit terminal-flat fixture releases it once.

No live-market session or funds deposit is required. Generated reports are
synthetic, never NIFTY returns or actual broker P&L. Leave the Production workspace
PAUSED/SIMULATION_ONLY and the optional journal reader disabled.
