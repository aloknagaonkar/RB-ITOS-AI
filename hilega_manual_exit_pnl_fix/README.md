# Manual exit P&L and decision-candle display fix

Requires the existing hilega_manual_exit_patch already installed. Changes presentation and the future manual closure timestamp; it does not clear safety blocks, re-arm, or submit orders.

Fixes:
- The existing decision-candle table includes MANUAL EXIT REQUESTED and confirmed MANUAL EXIT events. Confirmed closure plus strategy-reset proof ends the previous UI lifecycle; fresh accepted entry starts the next. Pending requests never become completed exits.
- Existing confirmed manual resets are read from their audit records/reset acknowledgements, so the fix can display already-completed exits without replaying an execution action. Original audit records remain immutable; no candle OHLC or NIFTY manual-exit price is fabricated.
- Manual-exit cards use confirmed BUY/SELL fill prices, quantities and P&L saved by reconciliation.
- A cancelled BUY with zero fills shows quantity0, requested quantity separately, P&L ₹0 and CANCELLED_UNFILLED. It is not labelled SELL ACK and no fill price or points are invented.
- A filled-and-closed manual leg shows SELL FILLED with confirmed P&L.
- Existing manual closure timestamps are read from event_timestamp, correcting the copied entry timestamp without rewriting old journal data. New closure records get a fresh timestamp.
- Missing actual execution evidence remains unavailable rather than silently becoming zero.
- Original automatic exits retain their current estimated quote-based display. Main aggregate headings remain estimated because they can include automatic quote estimates; individual manual basket labels identify confirmed results.

Nineteen Python tests and four frontend label checks pass locally, including the generated existing dashboard function with injected store/config, zero-fill cancellation, positive/negative fill P&L, timestamps, old automatic projection and installer compatibility. Full TypeScript/Vite build must run on the VM.

Extract into RB-ITOS-AI root, then validate/tests BEFORE applying:

```bash
source .venv/bin/activate
python hilega_manual_exit_pnl_fix/install.py --check
PYTHONPATH=backend python -m unittest discover -s hilega_manual_exit_pnl_fix/tests
python hilega_manual_exit_pnl_fix/install.py
npm --prefix frontend run build
node hilega_manual_exit_pnl_fix/tests/test_short_rule.cjs .
```

The installer validates every anchor and Python syntax before any write, backs up changed files, and refuses unknown versions/reinstallation. After successful build, restart the API and Sandbox worker:

```bash
bash scripts/restart_api_only.sh
bash scripts/stop_hilega_upstox_sandbox_worker.sh
bash scripts/start_hilega_upstox_sandbox_worker.sh
```

Refresh with Ctrl+F5. Existing records are projected correctly; do not request another exit merely to repair display.

## Readiness FAIL is a separate execution-state check

This display fix does not establish why Sandbox readiness failed and does not make an unresolved exit safe. Collect:

```bash
bash scripts/status_hilega_upstox_sandbox_worker.sh
PYTHONPATH=backend python -m market_lab.hilega_manual_exit_v1 --status
```

The important fields are entries_blocked/failure_reason, uncertain_requests, worker running/session/strategy/armed, and manual status/last_error/completed_at. READY_FOR_FRESH_SIGNAL is expected after full verified closure and coordinator acknowledgement, while applicable session cutoff/kill-switch rules still remain. Do not delete recovery ledgers or re-arm to erase the failure.
