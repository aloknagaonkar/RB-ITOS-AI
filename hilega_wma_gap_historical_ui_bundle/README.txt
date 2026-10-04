HILEGA WMA-GAP HISTORICAL REPLAY + DAILY METRICS

This bundle integrates the already-tested ordered WMA-gap candidate into the
existing Hilega same-page Historical Replay UI.

It adds:
- HILEGA_WMA_GAP_V2_REPLAY as an observation-only historical strategy.
- Daily comparison rows for LIVE_RECORDED_V1, HILEGA_V1_REPLAY and WMA-gap V2.
- Gross Nifty points gained, gross points lost, net points, win/loss counts,
  gain/loss ratio and win rate.
- Losses avoided and profitable v1 signals denied.
- Existing View audit inspection enriched with every WMA-gap step, observed
  value, requirement, PASS/FAIL/WAIT status and explanation.

Prerequisite:
  data/historical-evidence/hilega-wma-gap-490-v1/trade-results.csv
  data/historical-evidence/hilega-wma-gap-490-v1/confirmation-attempts.csv

If absent, run:
  PYTHONPATH=backend:. python scripts/backtest_hilega_wma_gap_490.py

Install:
  python hilega_wma_gap_historical_ui_bundle/install.py
  ./scripts/restart.sh

Safety:
- Historical/research only.
- Existing live strategy and append-only audit are not modified.
- No broker request, order, paper order, quantity or execution path is enabled.
