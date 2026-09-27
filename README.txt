60-SESSION SETUP-FAMILY TAXONOMY V1.1
========================================

This package reruns the SAME latest 60 sessions.

Only one research definition changes:

Family C lifecycle termination
------------------------------
BULLISH C (GREEN-origin):
  terminate the stale C lifecycle if price closes below the RED low
  before the bullish C rebreak.

BEARISH C (RED-origin):
  terminate the stale C lifecycle if price closes above the GREEN high
  before the bearish C rebreak.

Why:
A continuation/re-entry lifecycle should not survive a decisive break of the
opposite opening structure and later reappear as the same trade after a regime
reversal. This is a structural/symmetric rule, not a time threshold.

Unchanged:
- Family B
- Family D
- Candidate A
- VWAP threshold
- +1/+3/+5/+10/+15 measurements
- causal MFE/MAE
- 15:15 onward excluded
- no production/runtime/order/execution changes

RUN 1 — rerun 60 sessions
-------------------------
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py \
  | tee /tmp/midpoint-vwap-60-session-validation-v1-1.txt

RUN 2 — overlap audit on corrected output
-----------------------------------------
python scripts/midpoint_vwap_60_session_overlap_lifecycle_audit_v1_1.py \
  | tee /tmp/midpoint-vwap-60-session-overlap-lifecycle-audit-v1-1.txt

CHECK BEFORE 120 SESSIONS
-------------------------
1. 25 Aug should retain:
   - 09:42 BEAR Family B
   - 12:00 BEAR Family C
   - 14:31 BULL Family D

2. 25 Aug 14:31 should no longer also appear as Family C.

3. Compare:
   - Family C event count before/after
   - exact C+D overlap count before/after
   - ±1/±3/±5m C+D overlap counts
   - chronological block counts
   - the unmeasured event count

Do not expand to 120 until this rerun is reviewed.
