B FAMILY — RUNNER TEMPO DIAGNOSTIC V17
========================================

Purpose
-------
Test whether the 12 canonical >=75-point Family-B runners naturally show
different expansion tempos.

No optimization is performed.

Measured intervals
------------------
entry -> +20
+20 -> +30
+20 -> +50
+20 -> +75
+20 -> +100
+50 -> +75
+75 -> +100

V17 also performs a descriptive median split on +20 -> +75:
FASTER_HALF / SLOWER_HALF

This median split is NOT a trading rule. It exists only to help diagnose whether
the runner population visibly separates into faster and slower expansion paths.

Run
---
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_runner_tempo_diagnostic_v17.py \
  | tee /tmp/b-family-runner-tempo-diagnostic-v17.txt

Paste the full output back.
