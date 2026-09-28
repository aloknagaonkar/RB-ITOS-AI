B FAMILY — V34.1 COMPLETE POINT-ACCOUNTING BASELINE
=====================================================

Purpose
-------
Complete point accounting for all 18 V32 degraded-state events using raw
underlying candles.

Reconstruct:
- lifecycle MFE
- structural invalidation exit points
- structural giveback
- degraded-trigger points
- rejected V29 exit points
- V29 later-new-MFE
- +50/+75/+100 preservation

Outputs a baseline scorecard for:
- STRUCTURAL_INVALIDATION
- V29_REJECTED_EXIT

From here onward every actual exit candidate should be compared against these.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_complete_points_baseline_v34_1.py \
  | tee /tmp/b-family-complete-points-baseline-v34_1.txt

Paste the complete output back.
