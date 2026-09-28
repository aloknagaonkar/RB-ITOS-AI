B FAMILY — V44 SECOND 100-SESSION DUAL-CANDIDATE HISTORICAL COMPARISON

Range:
2025-02-06 through 2025-07-16

Candidate A:
W3 / AGE30 primary + CAP20 rescue

Candidate B:
PRIMARY OFF + CAP20 rescue

No tuning grid.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_dual_candidate_validation_v44.py \
  | tee /tmp/b-family-dual-candidate-validation-v44.txt

Paste the complete output back.
