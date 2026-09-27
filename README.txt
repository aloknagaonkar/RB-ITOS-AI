MIDPOINT + VWAP SETUP-FAMILY VALIDATION — 60 SESSIONS — V1

Purpose
-------
Validate the three newly identified research families over the latest 60
opening-framework sessions before expanding to 120/180:

B) Delayed full Candidate A
C) Failed midpoint reclaim + fresh boundary rebreak
D) Full-range opposite-direction recovery/rebreak

Important
---------
- 15:15 onward excluded.
- Original Candidate A unchanged.
- No threshold search.
- No production changes.
- MFE/MAE is causal and starts after the completed entry candle.
- MFE/MAE stops before midpoint structural invalidation.

Family D deliberately does NOT require the exact 25-Aug midpoint pullback.
The pullback is recorded as a feature only; requiring it would overfit that day.

Run
---
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_vwap_60_session_setup_family_validation.py \
  | tee /tmp/midpoint-vwap-60-session-setup-family-validation-v1.txt

Sanity check
------------
The 25-Aug section should approximately show:
- Family B BEAR around 09:42
- Family C BEAR around 12:00
- Family D BULL around 14:31

If those do not appear, stop and inspect before interpreting aggregate results.
