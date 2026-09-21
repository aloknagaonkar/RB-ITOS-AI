CONTROL FAILURE MOVE-START PROXIMITY V6.3
=========================================

Purpose
-------
Evaluate the existing expiry-aware V6.2 control-failure events specifically
around the retrospective confirmed directional move starts.

This version DOES NOT:
- change V5 signal logic
- change expiry-aware basket selection
- change exact-strike behavior
- rebuild historical OI

It only changes attribution/evaluation.

Method
------
For each confirmed move start:
- use only SAME-DIRECTION V6.2 events
- search fixed windows:
  ±5m
  ±10m
  ±15m
  ±20m
  ±30m
- select the nearest candidate
- if equal distance, prefer the pre/at-move candidate
- report:
  lead/lag
  absolute distance from move start
  component order
  selected wings
  ATM state and breadth
  imbalance / velocity / acceleration
  +5/+10/+15/+30
  MFE/MAE

Primary research window:
±15 minutes

The component-order study is repeated INSIDE that ±15m move-start neighborhood:
- SAME_CANDLE
- FAILURE_THEN_DECAY
- DECAY_THEN_FAILURE

Copy
----
scripts/validate_control_failure_move_start_proximity_v6_3.py
tests/test_validate_control_failure_move_start_proximity_v6_3.py

Test
----
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest   tests/test_validate_control_failure_move_start_proximity_v6_3.py -v

Run
---
python scripts/validate_control_failure_move_start_proximity_v6_3.py

Inputs reused
-------------
data/historical-evidence/control-failure-expiry-aware-v6-2/
  control-failure-events-expiry-aware-v6-2.csv
  expiry-aware-validation-matrix-v6-2.csv

data/historical-evidence/
  trend-day-move-start-oi-replay-v1.json

Outputs
-------
data/historical-evidence/control-failure-move-start-proximity-v6-3/
  move-start-proximity-detail-v6-3.csv
  move-start-proximity-summary-v6-3.csv
  move-start-proximity-order-study-v6-3.csv
  move-start-proximity-summary-v6-3.json

Interpretation
--------------
lead_lag_minutes = signal_time - confirmed_move_start_time

negative = signal BEFORE move start
0        = signal at move start
positive = signal AFTER move start

The primary question:
Does the current control-failure theory produce a same-direction event within
about ±15 minutes of the confirmed directional move start?
