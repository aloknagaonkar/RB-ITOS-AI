# Midpoint Nifty column parity

Displays recorded Nifty price prominently, followed by entry price and direction-adjusted points. Bullish=current-entry; bearish=entry-current. Pre-entry health snapshots show no trade P&L. Baseline actual exits retain final entry-to-exit points. Candidate exits remain candidates and do not close baseline tracking. No strategy, exit rule, order, Sandbox arm, journal or immutable audit changes.

The supplied 703 October 9 rows have zero arithmetic mismatches. Repeated prices from 15:14 through 15:28 remain a separate freshness investigation: this patch does not validate or replace those recorded prices and does not turn the open trade's +147.45 into realized profit.

Extract in ~/RB-ITOS-AI, then:
```bash
source .venv/bin/activate
python midpoint_nifty_column_parity_bundle/install.py &&
./scripts/restart.sh
```
Refresh browser after restart. Existing Sandbox remains session-armed; verify scripts/status_hilega_upstox_sandbox_worker.sh afterwards. Installer guards source hashes and restores files/frontend output if validation fails. Nine point/lane/terminal tests and frontend build pass. Baseline session closure and market freshness are not claimed fixed.
