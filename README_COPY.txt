Branch C V2.2 — 120-session Forward Outcome Audit

Purpose
-------
Keep the Branch C state machine frozen and measure actual Nifty forward
price behavior after each candidate bullish state.

Signal groups
-------------
OPENING_BULLISH_CONFIRMED
INTRADAY_BULLISH
INTRADAY_STRONG
INTRADAY_FULL

Opening logic
-------------
09:15 FULL alignment
09:20 RSI > WMA
09:25 RSI > WMA
=> OPENING_BULLISH_CONFIRMED

Normal intraday progression
---------------------------
RSI↑EMA -> ARMED
RSI↑WMA -> ACTIVE_SETUP
RSI > 50 -> INTRADAY_BULLISH
EMA3 > WMA -> INTRADAY_STRONG
all >50 and RSI > EMA3 > WMA -> INTRADAY_FULL

Shared invalidation
-------------------
first RSI↓WMA -> WEAKENING
next candle still RSI < WMA -> BULLISH_END
next candle recovers RSI > WMA -> CONTINUATION

Measured outcomes
-----------------
close move at:
+5m
+10m
+15m
+30m
+60m

also:
MFE until BULLISH_END/session end
MAE until BULLISH_END/session end
time to MFE
time to MAE
move at BULLISH_END

No option premium data is used yet.

Run tests
---------
python -m pytest tests/test_validate_hilega_milega_forward_outcome_v2_2.py -v

Run 120-session audit
---------------------
python scripts/validate_hilega_milega_forward_outcome_v2_2.py \
  --end-date 2026-09-21 \
  --trading-sessions 120 \
  --calendar-lookback-days 190 \
  --intraday-date 2026-09-21

Outputs
-------
data/historical-evidence/branch-c-forward-outcome-v2-2.csv
data/historical-evidence/branch-c-forward-outcome-summary-v2-2.csv

Paste back
----------
=== SUMMARY ===
plus any dates you want manually inspected.
