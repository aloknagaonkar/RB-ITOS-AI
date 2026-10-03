HILEGA ENTRY FILTER CANDIDATES — 490-SESSION RESEARCH
=====================================================

Purpose
-------
Compare three predeclared, observation-only entry-health outputs against the
same immutable 490-session Hilega trade dataset:

1. WMA_FLAT_WARNING
   Tags abs(WMA21-RSI OLS3 slope) <= 0.10.  It never rejects a trade.

2. LARGE_GAIN_ALIGNMENT
   Keeps a trade only when all five entry-time conditions support direction:
   RSI side of 50, EMA/WMA position, RSI slope, EMA slope, and WMA slope > 0.10.

3. FLAT_WMA_CONFIRMATION_FILTER
   Rejects only when WMA is flat and at least two are weak:
   EMA/WMA gap expansion, RSI slope, and EMA slope.

Input
-----
data/historical-evidence/hilega-alignment-points-490-v1/
  trade-alignment-points.csv

Installed files
---------------
scripts/
  research_hilega_entry_filter_candidates.py
tests/
  test_research_hilega_entry_filter_candidates.py

Install
-------
cd ~/RB-ITOS-AI
source .venv/bin/activate
python hilega_entry_filter_candidates_bundle/install.py

Run
---
PYTHONPATH=backend:. python \
  scripts/research_hilega_entry_filter_candidates.py

Outputs
-------
data/historical-evidence/hilega-entry-filter-candidates-490-v1/
  report.json
  candidate-summary.csv
  flat-warning-summary.csv
  candidate-route-summary.csv
  flat-confirmation-reasons.csv
  trade-candidate-decisions.csv

Validation design
-----------------
- All rule features exist at entry and use completed candles.
- Large moves use the direction-specific IS 90th-percentile MFE threshold.
- Those IS thresholds remain frozen for OOS.
- Results are printed separately for bullish and bearish directions.
- Route-level results reveal whether a result is isolated to one route.
- Rejected trades contribute zero counterfactual points.

Safety
------
Research only. No live strategy, service, audit, configuration, order, paper
order, or quantity is changed. No restart is required.
