HILEGA 490-SESSION ALIGNMENT-TO-POINTS RESEARCH
================================================

Purpose
-------
1. Extend Hilega history to 490 analysis sessions plus 10 warm-up sessions.
2. Replay the unchanged canonical bullish/bearish Hilega V1 coordinator.
3. Attribute actual entry-to-exit NIFTY points, MFE, MAE and giveback to
   RSI9 / EMA3(RSI9) / WMA21(RSI9) alignments.
4. Treat a flat WMA as WAIT evidence. REVERSAL_RISK requires joint WMA, EMA,
   RSI and EMA-WMA-gap deterioration.

Nothing in this bundle changes or enables a live trading rule.

Installed folder structure
--------------------------
scripts/
  materialize_hilega_490_sessions.py
  research_hilega_alignment_points_490.py
tests/
  test_research_hilega_alignment_points_490.py

Install
-------
cd ~/RB-ITOS-AI
source .venv/bin/activate
python hilega_alignment_points_490_bundle/install.py

Run sequence
------------
Step 1: acquire enough immutable cache sessions

PYTHONPATH=backend:. python \
  scripts/materialize_hilega_490_sessions.py

The materializer requires 500 valid sessions: 490 analysis sessions and 10
leading context sessions. Existing cache files are never overwritten.

Step 2: regenerate canonical indicator features

PYTHONPATH=backend:. python \
  scripts/audit_hilega_indicator_dataset_v2.py

Step 3: replay the unchanged strategy and attribute points

PYTHONPATH=backend:. python \
  scripts/research_hilega_alignment_points_490.py

Outputs
-------
data/historical-evidence/hilega-alignment-points-490-v1/
  materialization-report.json
  report.json
  trade-alignment-points.csv
  trade-health-timeline.csv
  alignment-summary.csv
  wma-state-summary.csv
  component-summary.csv
  daily-points.csv

Interpretation
--------------
- captured_points: bullish exit-entry; bearish entry-exit.
- MFE/MAE start only after entry. Entry-bar extremes are not counted.
- A 14:55 OPEN cutoff does not use the later range of that five-minute bar.
- WMA is WMA21(RSI9), not a WMA of NIFTY price.
- FLAT alone is never labeled a reversal.
- The first 70% of analysis sessions is IS; the latest 30% is locked OOS.
- Do not choose a threshold from OOS and rerun it repeatedly.
- Option premiums, spreads, charges and quantity are outside this study.

Safety
------
Research only. No service restart, live audit change, strategy gate, order,
paper order or quantity change.
