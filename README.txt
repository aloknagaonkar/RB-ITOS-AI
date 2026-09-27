B FAMILY — 180-SESSION DATA HEALTH AUDIT V14
================================================

Purpose
-------
Formal PASS/FAIL gate before running trailing-SL characterization.

Checks
------
- 180-session universe
- underlying 1m coverage
- futures/VWAP 1m coverage
- duplicate timestamps
- missing timestamps in trusted 09:15–15:14 window
- session_vwap nulls
- frozen canonical B parity:
    total = 45
    older = 27
    latest60 = 18

Run
---
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_180_data_health_audit_v14.py \
  | tee /tmp/b-family-180-data-health-v14.txt

Do not proceed to trailing-SL V15 unless STATUS=PASS.

Research only. No production/runtime/execution changes.
