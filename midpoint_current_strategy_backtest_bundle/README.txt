MIDPOINT CURRENT STRATEGY — FULL BACKTEST
=========================================

Folder placement:

  ~/RB-ITOS-AI/midpoint_current_strategy_backtest_bundle/

Install the file:

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_current_strategy_backtest_bundle/install.py

Run all 480 historical sessions:

  PYTHONPATH=backend:. python scripts/backtest_midpoint_current_strategy.py

Optional date range:

  PYTHONPATH=backend:. python scripts/backtest_midpoint_current_strategy.py \
    --start 2026-09-01 --end 2026-09-29

Default outputs:

  data/historical-evidence/hilega-pcr-oi-support-research-v1/
  midpoint-current-strategy-full-backtest-v1/report.json
  midpoint-current-strategy-full-backtest-v1/trades.csv

Included:
  - B, E and C entries
  - exact +20 proof and proof+10 classifier
  - structural baseline
  - NORMAL_B_PROVED three-tier exit candidate
  - RUNNER_STRENGTHENING degraded exit candidate
  - MFE, MAE, duration and candidate-versus-structural comparison
  - family, direction, route, exit policy, block and monthly summaries

Excluded:
  - D, PM_E and DHANUSH entries
  - option premium, spreads, slippage, charges and quantity

This is read-only and does not restart or modify any live process.
