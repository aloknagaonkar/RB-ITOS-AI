B FAMILY — V42 PRIMARY-EXIT RETUNING WITH CAP20 FIXED
==========================================================

V41 result on 43 events:
baseline      +2416.05
CAP20         +2370.35
difference      -45.70

Important decomposition:
NO_RESCUE / V35-primary-only policy was -168.35 vs baseline.
CAP20 rescue added +122.65 points back.

So V42 keeps CAP20 rescue fixed and retunes ONLY the V35 primary exit.

Primary candidates:
- OFF
- weakening streak 1 / 2 / 3
- min degraded age 5 / 10 / 15 / 20 / 30 minutes

Goal:
remove the remaining ~45.70-point shortfall while keeping strong
+75/+100 chase and reasonable drawdown.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_primary_exit_retuning_v42.py \
  | tee /tmp/b-family-primary-exit-retuning-v42.txt

Paste the complete output back.
