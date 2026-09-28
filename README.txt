B FAMILY — V33 RECOVERY ATTEMPT SEQUENCE DIAGNOSTIC
====================================================

Purpose
-------
Study recovery-attempt sequences inside V32 DEGRADED states.

Compare RECOVERED vs FAILED_RECOVERY paths using:
- first attempt
- second attempt
- recovery gain
- gap-to-target progression
- improving vs weakening transitions
- longest consecutive weakening streak
- spacing between attempt peaks

No thresholds are selected.
No exit rule is defined.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_recovery_attempt_sequence_v33.py \
  | tee /tmp/b-family-recovery-attempt-sequence-v33.txt

Paste the complete V33 output back.
