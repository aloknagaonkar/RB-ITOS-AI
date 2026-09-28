MIDPOINT PRE-CONFIRMED / MATURE VWAP AT BOUNDARY — V51

This tests the pattern observed on 2026-09-28 without changing Family B.

Research definition:
At the structural boundary break, futures-VWAP is already directionally beyond
the frozen +/-5 threshold, while canonical fresh Candidate A at the boundary
is false. This is labeled MATURE_A_AT_BOUNDARY.

The script compares:
- MATURE_A_AT_BOUNDARY
- FRESH_A_AT_BOUNDARY
- NO_A_AT_BOUNDARY

Measures:
- MFE / MAE in underlying points
- +20/+30/+50/+75/+100 opportunities
- 5/10/15/30 minute directional close moves
- mature VWAP streak length at the boundary
- bullish/bearish splits

Run:
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend
python scripts/midpoint_preconfirmed_boundary_scan_v51.py

Then:
cat data/historical-evidence/hilega-pcr-oi-support-research-v1/midpoint-preconfirmed-boundary-v51/summary-v51.txt

Important:
This is retrospective research on already-used history, not untouched OOS.
No live strategy/runtime files are modified.
No execution or orders are enabled.
