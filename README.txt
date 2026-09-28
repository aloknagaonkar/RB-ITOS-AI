B FAMILY — V41 43-EVENT RESCUE CONTRIBUTION + CAP RETUNING
================================================================

V40.1 result:
baseline   +2416.05
V38_CAP50  +2091.80
delta       -324.25

Risk improved, but total points fell.

V41 isolates the likely issue: the rescue layer.

Tests on the same 43 events:
- NO_RESCUE
- CAP0
- CAP10
- CAP20
- CAP30
- CAP40
- CAP50

CAP60/75/100 are printed as INCOMPLETE diagnostics because V40.1 did not retain
rescue candidates that were skipped by CAP50.

V35 primary logic remains fixed.
No entry changes.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_rescue_cap_retuning_v41.py \
  | tee /tmp/b-family-rescue-cap-retuning-v41.txt

Paste the complete output back.
