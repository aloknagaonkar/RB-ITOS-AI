CONTROL FAILURE EXPIRY-AWARE VALIDATION V6.2
=============================================

This version does TWO things together:

1) Corrects basket width using the frozen expiry-aware rule:
   expiry day / 0 sessions left -> ATM ±1
   1 trading session left       -> ATM ±2
   2 trading sessions left      -> ATM ±3
   3 trading sessions left      -> ATM ±4
   4+ trading sessions left     -> ATM ±5

   Example:
   Wednesday -> next Tuesday expiry
   Thu, Fri, Mon, Tue = 4 sessions left -> ATM ±5

2) Runs the earlier suggested component-order study on the corrected
   expiry-aware events:
   SAME_CANDLE
   FAILURE_THEN_DECAY
   DECAY_THEN_FAILURE

   It reports:
   - event count
   - unique sessions
   - average + median lead/lag to retrospective move start
   - average + median +5/+10/+15/+30 directional movement
   - average + median MFE/MAE
   - +15m and +30m positive-direction hit rates
   - same-direction vs opposite-direction events

Important:
- Existing V5 control-failure logic is NOT changed.
- Exact physical strikes only.
- No nearest-strike fallback.
- No interpolation.
- Unavailable historical sessions remain unavailable.
- Uses exact expiry stored in each positioning.json.
- Trading-session count currently means Mon-Fri sessions between
  session date (exclusive) and expiry (inclusive). The mapping is printed
  for every date so holiday edge cases can be audited explicitly.

Copy into ~/RB-ITOS-AI preserving folders:
scripts/validate_control_failure_expiry_aware_v6_2.py
tests/test_validate_control_failure_expiry_aware_v6_2.py

TEST
----
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest   tests/test_validate_control_failure_expiry_aware_v6_2.py -v

RUN
---
python scripts/validate_control_failure_expiry_aware_v6_2.py

The script reuses the historical positioning.json files already built.
It does NOT rebuild the 36 sessions.

OUTPUTS
-------
data/historical-evidence/control-failure-expiry-aware-v6-2/
  expiry-aware-inventory-v6-2.csv
  control-failure-events-expiry-aware-v6-2.csv
  expiry-aware-validation-matrix-v6-2.csv
  component-order-study-v6-2.csv
  expiry-aware-validation-summary-v6-2.json
  v5-pm1/
  v5-pm2/
  v5-pm3/
  v5-pm4/
  v5-pm5/

CHECK FIRST
-----------
The console prints:

=== EXPIRY-AWARE BASKET MAP ===
DATE | direction | expiry | sessions_left | wings | basket size | status

Verify this mapping before interpreting results.

The most important final console section is:

=== EARLIER SUGGESTED TEST: COMPONENT ORDER STUDY ===

This is the earlier test requested:
- SAME_CANDLE vs FAILURE_THEN_DECAY vs DECAY_THEN_FAILURE
- after applying the correct expiry-aware basket width.
