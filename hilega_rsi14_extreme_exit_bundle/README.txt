HILEGA RSI14 EXTREME EXIT RESEARCH

Purpose
-------
Compare the existing completed-5m RSI9/WMA21 exit with two research-only
RSI14 extreme exits on the same accepted-entry population:

1. RSI14_EXTREME_LEVEL_5M
   - Bullish: first completed 5m RSI14 >= 70.
   - Bearish: first completed 5m RSI14 <= 30.

2. RSI14_EXTREME_AFTER_PLUS20_5M
   - The same directional RSI14 threshold, but only after +20 proof.

Install and run
---------------
  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python hilega_rsi14_extreme_exit_bundle/install.py

  PYTHONPATH=backend:. python \
    scripts/research_hilega_rsi14_extreme_exits.py

Outputs
-------
  data/historical-evidence/hilega-rsi14-extreme-exits-490-v1/report.json
  data/historical-evidence/hilega-rsi14-extreme-exits-490-v1/headline.csv
  data/historical-evidence/hilega-rsi14-extreme-exits-490-v1/policy-trades.csv
  data/historical-evidence/hilega-rsi14-extreme-exits-490-v1/candidate-exits.csv
  data/historical-evidence/hilega-rsi14-extreme-exits-490-v1/selected-date-examples.csv

The report separates ALL, BULLISH and BEARISH for development, observed
forward, all 490 sessions, and recent/prior/earlier 30-session windows.

Safety
------
Research only. It does not change live strategy, services, audit decisions,
orders, paper orders, or quantity.
