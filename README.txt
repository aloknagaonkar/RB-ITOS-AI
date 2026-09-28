B FAMILY — V34.2 COMPARABLE 18-EVENT POINTS BASELINE
=====================================================

Purpose
-------
Create one same-population 18-event points baseline before V35.

Baseline:
STRUCTURAL_OR_SESSION_CUTOFF
- structural invalidation close if present
- otherwise final trusted 1-minute session close

V29:
Reconstructed using the exact frozen multi-episode scan.
If V29 never exits, the policy falls back to the common baseline so all
18 events remain comparable.

Metrics:
- total / mean / median / worst / best
- max drawdown
- improvement vs baseline
- +50/+75/+100 preservation
- later new MFE after actual V29 exits

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_comparable_points_baseline_v34_2.py \
  | tee /tmp/b-family-comparable-points-baseline-v34_2.txt

Paste the complete output back.

After V34.2:
- freeze the first true V35 exit candidate
- test on OOS
- compare point scorecard against this baseline
