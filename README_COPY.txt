CONTROL FAILURE COMPONENT TIMESTAMP ATTRIBUTION V6.4
=====================================================

Purpose
-------
Explain why the V6.3 matched signals were commonly +5 minutes after the
retrospective confirmed move start.

V6.4 DOES NOT change:
- V5 control-failure signal logic
- expiry-aware basket selection
- exact-strike rules
- any strategy/execution logic

It only decomposes the already matched PRIMARY ±15m V6.3 events.

For every matched event it prints:
- session date
- known direction
- retrospective move-start time
- event/signal checkpoint and lead/lag
- failure checkpoint and lead/lag
- decay checkpoint and lead/lag
- signal candle start/end
- whether the move start occurred inside the signal candle
- earliest component and its lead/lag
- closest component and its lead/lag
- +15m / +30m directional follow-through

Lead/lag definition
-------------------
timestamp - retrospective_move_start

negative = before move start
0        = at move start
positive = after move start

Important
---------
±15m remains an EVALUATION window only. It is not part of the live signal rule
and introduces no future data into signal generation.

Copy
----
scripts/validate_control_failure_component_timestamp_v6_4.py
tests/test_validate_control_failure_component_timestamp_v6_4.py

Test
----
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest   tests/test_validate_control_failure_component_timestamp_v6_4.py -v

Run
---
python scripts/validate_control_failure_component_timestamp_v6_4.py

Inputs reused
-------------
data/historical-evidence/control-failure-expiry-aware-v6-2/
  control-failure-events-expiry-aware-v6-2.csv

data/historical-evidence/control-failure-move-start-proximity-v6-3/
  move-start-proximity-detail-v6-3.csv

Outputs
-------
data/historical-evidence/control-failure-component-timestamp-v6-4/
  component-timestamp-detail-v6-4.csv
  component-timestamp-summary-v6-4.csv
  component-timestamp-summary-v6-4.json

Main question
-------------
When V6.3 says the matched signal was +5m after move start:
- was the first FAILURE/DECAY component already present at 0m or -5m?
- did the retrospective move start occur inside the 5m signal candle?
