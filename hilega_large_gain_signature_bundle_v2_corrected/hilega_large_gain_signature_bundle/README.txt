HILEGA LARGE-GAIN SIGNATURE + STRICT FLAT-WMA RESEARCH
======================================================

Purpose
-------
This read-only layer consumes the completed 490-session trade file and answers:

1. Does a strict flat-WMA no-trade filter improve points in both IS and OOS?
2. How many large moves would that filter incorrectly reject?
3. What were the exact RSI9, EMA3(RSI9), WMA21(RSI9), EMA-WMA gap and
   three-bar slopes when the largest 10% of MFE moves began?
4. Does an IS-derived high-probability signature retain performance in OOS?

WMA here is WMA21 of RSI9, not a price WMA.

Installed files
---------------
scripts/
  research_hilega_large_gain_signatures.py
tests/
  test_research_hilega_large_gain_signatures.py

Install
-------
cd ~/RB-ITOS-AI
source .venv/bin/activate
python hilega_large_gain_signature_bundle/install.py

Prerequisite
------------
The earlier alignment-to-points run must have created:

data/historical-evidence/hilega-alignment-points-490-v1/
  trade-alignment-points.csv

Run
---
PYTHONPATH=backend:. python \
  scripts/research_hilega_large_gain_signatures.py

Outputs
-------
data/historical-evidence/hilega-large-gain-signatures-490-v1/
  report.json
  flat-wma-sensitivity.csv
  large-gain-trades.csv
  cohort-feature-comparison.csv
  sweet-spot-validation.csv
  trade-signature-scores.csv

Predeclared mathematics
-----------------------
- Primary flat WMA: abs(three-bar OLS WMA21-RSI slope) <= 0.10 indicator
  units per completed five-minute bar.
- Sensitivity only: 0.05, 0.10, 0.15, 0.20 and 0.30.
- Large gain: direction-specific IS 90th-percentile MFE threshold.
- The frozen IS threshold is applied to OOS; OOS never chooses the threshold.
- Sweet-spot ranges: IS large-MFE p10-p90 ranges of direction-normalized RSI
  level, EMA-WMA gap, RSI slope, EMA slope, WMA slope and gap slope.
- Candidate score: directional WMA slope > 0.10 and at least four of six
  frozen ranges pass.
- Slope angles are atan(slope) in indicator space only. They are reported for
  inspection but are not chart-invariant trading rules.

Decision requirement for strict no-trade
----------------------------------------
Strict flat-WMA exclusion is supported only if:

1. rejected trades have negative points in IS and OOS,
2. kept-trade profit factor improves in IS and OOS,
3. OOS improvement is not driven by one outlier, and
4. the percentage of top-decile MFE moves rejected is acceptable.

Safety
------
No live rule, strategy configuration, service, audit, order, paper order or
quantity is modified.
