MIDPOINT PM B/E HISTORICAL BACKTEST V1
=====================================

Copy this whole folder into the RB-ITOS-AI repository root, then run:

  source .venv/bin/activate
  python midpoint_pm_be_backtest_bundle/install.py

Run all 480 historical sessions:

  PYTHONPATH=backend:. python scripts/backtest_midpoint_pm_be.py

Optional date range:

  PYTHONPATH=backend:. python scripts/backtest_midpoint_pm_be.py \
    --start 2026-08-01 --end 2026-09-30

Outputs:

  data/historical-evidence/hilega-pcr-oi-support-research-v1/
    midpoint-pm-be-backtest-v1/report.json
    midpoint-pm-be-backtest-v1/pm-trades.csv

The replay temporarily enables PM B/E only in memory. It does not change the
live PM gate, restart services, touch the live audit, or send orders.
