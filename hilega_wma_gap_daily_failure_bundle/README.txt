HILEGA WMA-GAP DAILY FAILURE ANALYSIS
=====================================

This research-only analyzer explains the ordered WMA-gap candidate day by day.

It creates:

  data/historical-evidence/hilega-wma-gap-490-v1/
    daily-failure-summary.csv
    daily-failure-trades.csv
    daily-failure-report.json

Daily loss measures
-------------------

1. Candidate realized losses:
   Accepted candidate entries whose candidate exit points were negative.

2. Denied winner opportunity:
   Canonical trades with positive final points that the candidate denied.

3. Lost versus canonical:
   max(0, canonical daily points - candidate daily points). This is the clean
   policy-level answer to "how much did the candidate lose that day?"

4. Adverse entry-delay cost:
   Accepted trades where candidate points were below canonical points. This is
   diagnostic and must not be added to realized loss because that can double
   count the same trade.

Install and run
---------------

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  unzip -o hilega_wma_gap_daily_failure_bundle_v1.zip
  python hilega_wma_gap_daily_failure_bundle/install.py

  PYTHONPATH=backend:. python \
    scripts/analyze_hilega_wma_gap_daily_failures.py

The terminal prints aggregate counts and the 25 worst dates. The CSV contains
all 490 sessions, with ALL, BULLISH and BEARISH rows for manual validation.

No live strategy, service, audit, order, paper order or quantity is changed.

