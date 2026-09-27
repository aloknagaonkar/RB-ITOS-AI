B FAMILY — LIFECYCLE-CONSISTENT RISK COMPARISON V8.2
======================================================

V8.2 fixes the key V8.1 methodology problem:
fixed/ATR models are no longer allowed to hold past canonical B structural
invalidation.

Models:
1. FIXED_15_LIFECYCLE
2. ATR_1.00_LIFECYCLE
3. STRUCTURAL
4. HYBRID_FIXED15_BE20
5. HYBRID_MIN15_ATR1_BE20

Hybrid logic:
- before +20: emergency risk
- after +20: breakeven floor + canonical structural exit
- no post-invalidation profit is allowed

The report also includes COMMON_ATR_ELIGIBLE comparisons so all models are
measured on the exact same ATR-available event set.

Run:
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_risk_model_comparison_v8_2.py \
  | tee /tmp/b-family-risk-model-comparison-v8-2.txt

Outputs:
data/historical-evidence/hilega-pcr-oi-support-research-v1/
  b-family-risk-model-comparison-v8-2/
    b-family-risk-model-events-v8-2.csv
    b-family-risk-model-summary-v8-2.txt

Research only.
Underlying NIFTY points are not CE/PE option-premium P&L.
