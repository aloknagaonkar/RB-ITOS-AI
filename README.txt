B FAMILY — V43 DUAL-CANDIDATE HISTORICAL COMPARISON
========================================================

Compare two frozen V42 candidates on a separate 100-session block:

2025-07-17 through 2025-12-11

Candidate A:
W3 / AGE30 primary + CAP20 rescue

Candidate B:
PRIMARY OFF + CAP20 rescue

No tuning grid.

Purpose:
determine whether the W3/AGE30 primary exit adds repeatable value, or whether
the simpler PRIMARY_OFF + CAP20 architecture is better.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_dual_candidate_validation_v43.py \
  | tee /tmp/b-family-dual-candidate-validation-v43.txt

Paste the complete output back.
