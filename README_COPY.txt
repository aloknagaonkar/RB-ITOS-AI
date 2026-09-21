CONTROL FAILURE FROZEN 36 VALIDATION V6
=======================================

Purpose
-------
Validate the unchanged V5 control-failure theory across the frozen
18 bullish + 18 bearish trend-day population.

Important methodology split
---------------------------
1. ALL_36_PM2_EXPLORATORY
   Keeps ATM ±2 on all 36 dates for direct comparability with current V5.

2. STRICT_D1_PM2_ONLY
   Treats ATM ±2 as strict only where expiry is tomorrow (DTE=1).
   Non-D1 sessions are clearly labeled exploratory, not silently treated
   as expiry-rule-valid.

No nearest strike fallback.
No interpolation.
Same physical strikes at T and T-5.
No strategy/execution changes.

Copy
----
scripts/validate_control_failure_frozen_36_v6.py
tests/test_validate_control_failure_frozen_36_v6.py

Test
----
cd ~/RB-ITOS-AI
source .venv/bin/activate
python -m pytest tests/test_validate_control_failure_frozen_36_v6.py -v

Inventory first
---------------
python scripts/validate_control_failure_frozen_36_v6.py

If positioning.json is missing for frozen dates, the script safe-stops and writes:
data/historical-evidence/control-failure-frozen-36-v6/frozen-36-inventory-v6.csv

Build missing dates when exact expiry can be resolved from existing historical evidence/cache
----------------------------------------------------------------------------------------------
python scripts/validate_control_failure_frozen_36_v6.py --build-missing

The build step does NOT guess expiry. Dates whose exact expiry cannot be resolved are left missing and the run safe-stops.

Final outputs after all 36 builds exist
---------------------------------------
data/historical-evidence/control-failure-frozen-36-v6/
  frozen-36-inventory-v6.csv
  frozen-36-validation-matrix-v6.csv
  frozen-36-validation-summary-v6.json
  v5/control-failure-events-v5.csv
  v5/control-failure-candles-v5.csv
  v5/control-failure-summary-v5.json

If a TREND_DAY_MOVE_START_OI_REPLAY_V1 artifact is auto-discovered (or passed via
--move-start-replay), the matrix also reports lead/lag minutes between the first
same-direction V5 event and the retrospective dominant move-start anchor.
