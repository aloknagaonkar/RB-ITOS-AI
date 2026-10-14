HILEGA RSI9 EXTREME EXIT RESEARCH

This runs the same extreme-level experiment previously run for RSI14, but
uses completed five-minute RSI9:

1. RSI9_EXTREME_LEVEL_5M
   Bullish exit at RSI9 >= 70; bearish exit at RSI9 <= 30.

2. RSI9_EXTREME_AFTER_PLUS20_5M
   Same thresholds, but eligible only after +20 proof.

Control
-------
The existing completed-five-minute RSI9/WMA21 crossover exit/session cutoff.

Install and run
---------------
  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python hilega_rsi9_extreme_exit_bundle/install.py

  PYTHONPATH=backend:. python \
    scripts/research_hilega_rsi9_extreme_exits.py

Output
------
  data/historical-evidence/hilega-rsi9-extreme-exits-490-v1/report.json
  data/historical-evidence/hilega-rsi9-extreme-exits-490-v1/headline.csv
  data/historical-evidence/hilega-rsi9-extreme-exits-490-v1/policy-trades.csv
  data/historical-evidence/hilega-rsi9-extreme-exits-490-v1/candidate-exits.csv
  data/historical-evidence/hilega-rsi9-extreme-exits-490-v1/selected-date-examples.csv

Research only. No live strategy, service, audit, order, paper order or
quantity is changed.
