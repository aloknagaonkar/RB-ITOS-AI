# Five actual Upstox Sandbox legs per Hilega signal

This replaces the one-ATM worker with a five-leg basket worker. The active trade section contains actual Sandbox submission records for ATM-2, ATM-1, ATM, ATM+1, ATM+2. The comparison section is removed. V2 has NO daily trade/order-count cap. One lot is submitted per leg, using the provider's current lot size. Existing live strategy and EMA10 historical research are unchanged.

From RB-ITOS-AI root, after extracting this bundle:

```bash
./scripts/stop_hilega_upstox_sandbox_worker.sh
python hilega_sandbox_five_leg_execution_bundle/install.py &&
./scripts/restart.sh &&
PYTHONPATH=backend:. python -m market_lab.hilega_upstox_sandbox_basket_v2 \
  --arm-session 2026-10-08 --confirm ARM_UPSTOX_SANDBOX_FIVE_LEGS &&
./scripts/start_hilega_upstox_sandbox_worker.sh &&
./scripts/status_hilega_upstox_sandbox_worker.sh
```

Use the intended current IST date if installing later. No --max-orders argument is used. Do not change the old HILEGA_UPSTOX_SANDBOX_MAX_ORDERS to zero: the V1 config validator still expects a positive value, but V2 does not apply it as a submission cap. Retain enabled=1, kill_switch=0 and lots=1 in the Sandbox configuration.

Installer refuses a running Sandbox PID, backs up source, runs regression tests and frontend build, and creates V2 control disarmed only if absent. It does not send orders, change credentials or alter V1 control/journals. API restart loads V2 dashboard routing. Shared start/status scripts now invoke V2; stop script continues to use the existing PID file. Refresh the UI after install/restart.

Arming verifies source audit integrity and starts at the current source sequence, so earlier trades are not replayed. It refuses migration with an open V1 position or unresolved V1 request/failure and refuses rearming while V2 has open or uncertain legs. Resolve these with broker evidence first; do not delete journals. No active single-contract position is automatically expanded into a basket. V1 history remains on disk and is excluded from V2 session P&L.

Execution:
- CE basket for bullish; PE basket for bearish.
- At entry, use analytics quotes/contracts to select nearest eligible expiry and nearest ATM, with two contiguous 50-point Nifty strikes on either side.
- Validate all five contracts before any order. Store the complete plan before sending five individual Sandbox MARKET BUY requests.
- Shadow exit sends SELL requests for the exact accepted entry contracts/quantities; expiry/ATM is not reselected at exit.
- Requests, acknowledgements, uncertain responses, blocked/skipped events and source identities are persisted per leg.
- Duplicate event requests do not create new submissions. A request without acknowledgement is never automatically retried.
- A partial BUY failure blocks further new entries. Subsequent shadow exit can SELL known acknowledged legs while armed. An uncertain leg needs operator reconciliation; it is not assumed rejected or filled.
- A partial SELL failure blocks new entries but continues attempts for the other known legs. The uncertain SELL is never duplicated.
- Explicit kill switch/disarm halts all submissions, including exits. The operator must reconcile remaining positions.
- Matching pre-arm shadow exits are skipped without a broker call. Unmatched exits and strategy changes block new entries and require inspection.

Dashboard:
- Each active/completed basket shows five leg rows with contract, quantity, submission status, entry/exit prices/times, BUY/SELL order IDs, current price and quote-based P&L.
- Partial baskets show NOT_SUBMITTED or SUBMISSION_UNCERTAIN, never fabricated acknowledgements.
- Totals combine only acknowledged Sandbox legs with known prices; missing-price counts and subtotal labels remain explicit.
- Current quotes are fetched in one batch; missing prices remain unavailable. Refresh timeout/stale banners are shown.
- ACCEPTED means provider acknowledgement, not a confirmed fill. No filled-position or broker-realized P&L claim is made. Estimated P&L excludes fees/slippage and uses reference quotes.
- Accepted order submissions is a count, not a quota. Five buys plus five sells normally makes ten per completed signal basket.

Paths:
- backend/market_lab/hilega_upstox_sandbox_basket_v2.py
- frontend/src/hilegaUpstoxSandboxDashboard.tsx
- data/live-observation/hilega-upstox-sandbox-v2/control.json
- data/live-observation/hilega-upstox-sandbox-v2/basket-events.jsonl
- Existing data/logs/hilega-upstox-sandbox-worker.log

Validation performed locally: 29 tests covering basket execution/dashboard, bridge, pre-arm guard, V1 transport and legacy dashboard; TypeScript/Vite build. Tests use fake transports and do not submit orders. VM and actual broker execution of the new five-leg path still require forward validation.
