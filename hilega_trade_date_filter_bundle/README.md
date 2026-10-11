# Hilega trade date filters

Exited shadow trade cards and completed five-leg Sandbox baskets each have a session-date selector and visible/total record count. Default is today when that date has trades, otherwise the latest available trade date. Active trades remain visible without date filtering. Cards show their session date. Overall lifetime P&L summaries remain unchanged and are not totals for the selected date.

Live Hilega candle audit displays today (IST) and the previous available audit session only. On Monday this normally means Monday plus Friday, rather than Sunday with no trading. Older evidence is retained for replay. Filtering limits rendered rows/cards but does not change backend audit retention or polling.

Extract in ~/RB-ITOS-AI and run:
```bash
source .venv/bin/activate
python hilega_trade_date_filter_bundle/install.py &&
./scripts/restart.sh
./scripts/status_hilega_upstox_sandbox_worker.sh
```
Refresh browser. No strategy, Sandbox arm, execution, quantity, journal or P&L calculation changes. TypeScript/Vite build and five date checks (IST rollover, weekend previous session, future exclusion, default selection, manual date) passed. Source hash guards and build rollback included.
