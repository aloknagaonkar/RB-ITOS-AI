B FAMILY — BIG-RUNNER EXIT DIAGNOSTIC V16.1
=============================================

Fix vs V16
----------
V16 incorrectly expected 10 canonical >=75-point B runners.

The canonical 45-event geometry actually contains:
- >=75-point runners: 12
- >=100-point runners: 10

The V15 table showed 10 >=75 opportunities only inside the COMMON_ATR_ELIGIBLE
subset. Two >=75 runners are ATR-ineligible, so the full canonical diagnostic
must retain all 12 rather than silently dropping them.

No strategy, trail, risk, entry, VWAP, or lifecycle logic changed.

Run
---
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_big_runner_exit_diagnostic_v16_1.py \
  | tee /tmp/b-family-big-runner-exit-diagnostic-v16-1.txt

Paste the full output back.
