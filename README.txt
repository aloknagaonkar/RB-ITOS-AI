B FAMILY — V24 COMBINED 200-SESSION VALIDATION
================================================

V24 does NOT fetch new market data and does NOT rerun Family-B detection.

It combines the already completed, frozen validation outputs from:

V23:
  2025-02-06 -> 2025-07-16
  100 sessions

V22:
  2025-07-17 -> 2025-12-11
  100 sessions

It reports:
- combined B geometry
- milestone reach
- 95% Wilson confidence intervals
- V22 vs V23 block stability
- bull/bear stability
- frozen V20 classifier outcomes
- RUNNER_STRENGTHENING vs NORMAL_B
- Newcombe 95% CI for classifier rate differences

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_combined_200_validation_v24.py \
  | tee /tmp/b-family-combined-200-v24.txt

Paste the complete V24 output back.

Important:
- no B changes
- no V20 changes
- no threshold search
- no exit optimization
- no production/runtime/order changes
