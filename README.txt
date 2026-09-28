B FAMILY — V35 EXIT OPTIMIZATION + POINT-IMPROVEMENT LEADERBOARD
=================================================================

Purpose
-------
Tune the degraded-state recovery-attempt exit on the current 18-event
development population.

Transparent search:
- weakening streak required: 1 / 2 / 3 / 4
- minimum degraded age: 0 / 3 / 5 / 10 minutes

Every candidate reports:
- total / mean / median / worst / best points
- max drawdown
- delta vs V34.2 baseline
- delta vs V29
- +30/+40/+50/+75/+100 chase success / preservation
- later-new-MFE after actual exits
- actual exits / fallbacks

The winner is DEVELOPMENT only.
After this, freeze the winner and validate it on separate OOS history.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_exit_optimization_v35.py \
  | tee /tmp/b-family-exit-optimization-v35.txt

Paste the complete V35 output back.
