MIDPOINT REPEATED B/E REARM RESEARCH V1
=======================================

Folder structure after installation:

  RB-ITOS-AI/
  |-- scripts/
  |   `-- backtest_midpoint_repeated_be_rearm.py
  `-- docs/
      `-- MIDPOINT_INITIAL_RISK_RESEARCH_CHECKLIST.md

Install:

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python midpoint_repeated_be_rearm_research_bundle/install.py

Run the 480-session research replay:

  PYTHONPATH=backend:. python \
    scripts/backtest_midpoint_repeated_be_rearm.py

Outputs:

  data/historical-evidence/hilega-pcr-oi-support-research-v1/
  midpoint-repeated-be-rearm-v1/report.json

  data/historical-evidence/hilega-pcr-oi-support-research-v1/
  midpoint-repeated-be-rearm-v1/trades.csv

  data/historical-evidence/hilega-pcr-oi-support-research-v1/
  midpoint-repeated-be-rearm-v1/first-generation-parity.csv

Research only. It does not modify or restart the live coordinator.
