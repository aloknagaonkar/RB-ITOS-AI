60-SESSION OVERLAP / LIFECYCLE AUDIT V1
========================================

This audit does NOT change the B/C/D definitions.

It reads the existing 60-session validation event CSV and reports:

Exact overlaps:
- B+C
- B+D
- C+D
- B+C+D

Near overlaps:
- within ±1 minute
- within ±3 minutes
- within ±5 minutes

It also prints:
- B-only / C-only / D-only exact clusters
- every exact multi-family event
- unmeasured events
- the complete 25-Aug B/C/D list

RUN
---
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_vwap_60_session_overlap_lifecycle_audit.py \
  | tee /tmp/midpoint-vwap-60-session-overlap-lifecycle-audit-v1.txt

STOP CONDITION
--------------
Do not expand to 120 sessions yet.
First inspect:
1. exact C+D overlap frequency
2. near C+D overlap frequency
3. whether 25-Aug 14:31 is an isolated or common overlap
4. the unmeasured Family C event
