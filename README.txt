PM T1/T2/T3 + FUTURES VWAP CONTEXT — 60 SESSIONS — V1
========================================================

This is the next PM / Family-E research step.

Reference:
  12:45–13:14 fixed 30-minute range

T1:
  first full boundary close-break

T2:
  midpoint recross in the opposite direction

T3:
  opposite full-boundary close-break

At T1/T2/T3 record:
  NIFTY futures close
  session VWAP
  futures close - VWAP
  5-minute change in close - VWAP
  whether VWAP direction agrees with the event direction

Then compare:
  T2 entry-style measurement
  versus
  T3 entry-style measurement

No VWAP filter is applied.
Candidate A/B remain unchanged.
B, C V1.1, D remain frozen.

RUN
---
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/afternoon_pm_t1_t2_t3_vwap_context_60_session_v1.py \
  | tee /tmp/afternoon-pm-t1-t2-t3-vwap-context-60-v1.txt

Expected 25 Aug:
  T1 ~13:24 bearish
  T2 ~13:52 bullish midpoint recross
  T3 ~13:53 bullish opposite-boundary break

15:15 onward excluded.
Research only.
