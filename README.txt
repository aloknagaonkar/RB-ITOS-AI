PACKAGE CONTENTS
================

1) docs/MIDPOINT_VWAP_BCD_RESEARCH_FREEZE_V1.md
   Formal research-definition freeze note for:
   - B
   - C V1.1
   - D

2) scripts/afternoon_pm_false_break_reversal_60_session_v1.py
   New PM false-break -> midpoint recross -> opposite-boundary-break study.

RUN
---
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/afternoon_pm_false_break_reversal_60_session_v1.py \
  | tee /tmp/afternoon-pm-false-break-reversal-60-v1.txt

Expected 25 Aug:
- first BEAR break around 13:24
- bullish midpoint recross around 13:52
- bullish opposite-boundary break around 13:53

No B/C/D changes.
No runtime/order/execution changes.
