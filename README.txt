B FAMILY — WARNING AGE / PROFIT SEGMENTATION V4
==================================================

This V4 pass studies WHY the same fixed recovery window behaves differently for
early weak warnings and late warnings after a B has already moved favorably.

It does NOT change frozen B entry logic.

Run:
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_60_session_warning_age_profit_v4.py \
  | tee /tmp/b-family-60-session-warning-age-profit-v4.txt

Requires:
- b-family-warning-recovery-events-v2.csv from V2.

Outputs:
data/historical-evidence/hilega-pcr-oi-support-research-v1/
  b-family-60-session-warning-age-profit-v4/
    b-family-warning-age-profit-events-v4.csv
    b-family-warning-age-profit-summary-v4.txt

V4 reports:
- entry -> warning minutes
- warning points
- pre-warning MFE
- percent of source MFE already achieved before warning
- recovery timing
- post-warning MFE
- whether recovery occurred within 3 minutes
- data-derived warning-age quartiles
- profitable vs nonprofitable warning state

Research only.
