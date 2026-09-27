B FAMILY — BIG-RUNNER EXIT DIAGNOSTIC V16
===========================================

Purpose
-------
Diagnose why V15 T1/T2 structural trails cut some >=75-point B runners early.

This is NOT another optimization pass.

V16 selects the 10 canonical B events whose structural-lifecycle MFE >= +75
points and prints:

- entry/origin/delay
- ATR and initial risk
- +20/+30/+50/+75/+100 first-reach timestamps
- V8.2 hybrid exit
- T1 proof, pivot confirmations, stop updates, exit
- T2 proof, pivot confirmations, stop updates, exit
- post-exit best favorable movement
- missed extension

Detailed stop/pivot lifecycle is written to runner-timeline-v16.csv.

Run
---
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_big_runner_exit_diagnostic_v16.py \
  | tee /tmp/b-family-big-runner-exit-diagnostic-v16.txt

Paste the full output back.

Research only. No production/runtime/execution changes.
