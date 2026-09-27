B FAMILY — RISK GEOMETRY V7
=============================

Purpose
-------
Before choosing a small SL, measure how much adverse excursion genuine B
winners actually require.

Uses all 45 canonical B events:
- 18 development
- 27 older validation

The script directly imports the canonical V1.1 B detector and measurement code.

Run
---
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_risk_geometry_v7.py \
  | tee /tmp/b-family-risk-geometry-v7.txt

Outputs
-------
data/historical-evidence/hilega-pcr-oi-support-research-v1/
  b-family-risk-geometry-v7/
    b-family-risk-geometry-events-v7.csv
    b-family-risk-geometry-milestones-v7.csv
    b-family-risk-geometry-weak-events-v7.csv
    b-family-risk-geometry-summary-v7.txt

What to inspect
---------------
For winners that reach +20/+30/+50/+75/+100:
- how much adverse excursion occurred BEFORE reaching the milestone?
- would 5/10/15/20/25/30-point stops already have been hit?
- did stop and target occur in the same 1m candle (ambiguous)?

For weak B events (MFE <20):
- how quickly do -5/-10/-15/-20/-25/-30 adverse moves appear?

Research only.
No stop or target is frozen by this script.
Underlying NIFTY points are not option-premium P&L.
