HILEGA WMA-GAP LOSS ATTRIBUTION V1
=================================

Purpose
-------
Explain where the ordered WMA + EMA/WMA-gap candidate gains and loses points.
The analysis is descriptive and research-only. It does not modify the canonical
Hilega lifecycle, live gates, services, audits, orders, paper orders or quantity.

Inputs
------
data/historical-evidence/hilega-wma-gap-490-v1/report.json
data/historical-evidence/hilega-wma-gap-490-v1/trade-results.csv
data/historical-evidence/hilega-wma-gap-490-v1/confirmation-attempts.csv

Fixed diagnostic buckets
------------------------
Confirmation latency from canonical signal to candidate entry:
  0-2m, 3-5m, 6-10m, >10m

Confirmation WMA strength:
  0.75-0.99, >=1.00

One-minute directional EMA3/WMA21 gap expansion:
  WEAK:   0 < delta <= 0.25
  MEDIUM: 0.25 < delta <= 0.75
  STRONG: delta > 0.75

Absolute directional EMA3/WMA21 gap at confirmation:
  NARROW:   0 < gap < 3
  MODERATE: 3 <= gap < 6
  WIDE:     gap >= 6

Install and run
---------------
  python hilega_wma_gap_loss_attribution_bundle/install.py

  PYTHONPATH=backend:. python \
    scripts/analyze_hilega_wma_gap_loss_attribution.py

Outputs
-------
data/historical-evidence/hilega-wma-gap-490-v1/loss-attribution/report.json
data/historical-evidence/hilega-wma-gap-490-v1/loss-attribution/accepted-trades.csv
data/historical-evidence/hilega-wma-gap-490-v1/loss-attribution/accepted-loss-trades.csv
data/historical-evidence/hilega-wma-gap-490-v1/loss-attribution/denied-trades.csv
data/historical-evidence/hilega-wma-gap-490-v1/loss-attribution/latency-summary.csv
data/historical-evidence/hilega-wma-gap-490-v1/loss-attribution/wma-tier-summary.csv
data/historical-evidence/hilega-wma-gap-490-v1/loss-attribution/gap-expansion-summary.csv
data/historical-evidence/hilega-wma-gap-490-v1/loss-attribution/absolute-gap-summary.csv
data/historical-evidence/hilega-wma-gap-490-v1/loss-attribution/combined-cells.csv

Interpretation guardrails
-------------------------
* Accepted loss, denied-winner opportunity and entry-delay cost are different
  views and can overlap economically. Do not add them into one loss total.
* Candidate points use the unchanged canonical exit.
* Entry-delay cost compares candidate entry with canonical entry at that same exit.
* All 490 sessions are already-inspected evidence. No live rule should be enabled
  from this report without a newly collected untouched confirmation cohort.
