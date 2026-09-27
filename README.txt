PACKAGE: TWO RESEARCH TESTS
===========================

1) Rejected-C mechanism decomposition
-------------------------------------
Classifies the 57 rejected former-C events by:
- structural-age bucket
- exact / near / later same-direction Family-D relationship

Run:
python scripts/midpoint_vwap_60_session_rejected_c_mechanism_decomposition.py \
  | tee /tmp/rejected-c-mechanism-decomposition-v1.txt


2) Afternoon 12:45–13:15 midpoint/boundary break study
-------------------------------------------------------
Interpretation used for "median of 30 min candle":
  midpoint = (HIGH + LOW) / 2

Reference period:
  12:45:00 through 13:14:59 = exactly 30 completed 1m bars

Observation:
  starts 13:15
  wick-only break does NOT count
  close above HIGH => bullish boundary break
  close below LOW  => bearish boundary break

Measures:
  first midpoint close above/below
  first full boundary break
  +1/+3/+5/+10/+15/+30/+60 minute directional movement
  causal MFE/MAE through 15:14
  whether the opposite boundary later breaks
  reference candle direction vs breakout direction
  exact 25-Aug result

Run:
python scripts/afternoon_1245_1315_midpoint_boundary_break_60_session.py \
  | tee /tmp/afternoon-1245-1315-break-study-v1.txt

Research only.
No production/runtime/Hilega/Candidate-A changes.
No 15:15+ data.
