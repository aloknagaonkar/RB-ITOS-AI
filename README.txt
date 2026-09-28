MIDPOINT MATURE-A-AT-BOUNDARY ROBUSTNESS — V52

Goal
----
Validate the exact V51 research definition across four date-separated blocks:

1. 2024-08-16 -> 2025-02-05
2. 2025-02-06 -> 2025-07-16
3. 2025-07-17 -> 2025-12-11
4. 2025-12-12 -> 2026-09-08

Frozen definition
-----------------
At structural boundary break T0:
- canonical Candidate A at T0 is FALSE
- raw futures close - VWAP is already directionally beyond +/-5
- no new streak threshold
- no direction-specific threshold
- no exit optimization
- entry geometry measured from boundary-break close
- terminal = first adverse midpoint close / trusted cutoff

Run
---
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_mature_boundary_robustness_v52.py

Then:
cat \
data/historical-evidence/hilega-pcr-oi-support-research-v1/\
midpoint-mature-boundary-robustness-v52/summary-v52.txt

Important
---------
The script discovers historical structural, underlying, and futures/VWAP CSVs by schema.
It STOPS if conflicting duplicate raw OHLC or futures/VWAP data is found.

This is research only.
It does not alter Family B or live-shadow runtime.
2026-09-28 remains separate fresh evidence.
