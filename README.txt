B FAMILY — V39 MILESTONE-AWARE RESCUE OPTIMIZATION
=====================================================

Current best raw-points result:
V38_CAP50 = +1233.75

But V38 preserves only:
+75  = 69.2%
+100 = 60.0%

V39 adds a runner lockout:
once a trade has already reached +50 / +75 / +100 before the rescue signal,
the rescue can be disabled and the trade continues.

Grid:
caps:
35 / 40 / 45 / 50 / 55 / 60

lockout:
NONE / +50 / +75 / +100

Goal:
keep V38-level points while improving +75/+100 runner preservation.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_milestone_aware_rescue_v39.py \
  | tee /tmp/b-family-milestone-aware-rescue-v39.txt

Paste the complete output back.
