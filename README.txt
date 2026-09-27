B FAMILY — RISK MODEL COMPARISON V8
=====================================

Compares:
A) FIXED_15
B) ATR_0.50 / ATR_0.75 / ATR_1.00
C) STRUCTURAL midpoint invalidation
D) HYBRID: fixed-15 emergency cap until +20, then structural exit

Run:
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_risk_model_comparison_v8.py \
  | tee /tmp/b-family-risk-model-comparison-v8.txt

Outputs:
data/historical-evidence/hilega-pcr-oi-support-research-v1/
  b-family-risk-model-comparison-v8/
    b-family-risk-model-events-v8.csv
    b-family-risk-model-summary-v8.txt

Research only.
Underlying NIFTY points are not option-premium P&L.
