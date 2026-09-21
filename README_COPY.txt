Branch C V2.1 — 120-trading-session opening robustness test

Goal
----
Validate the proposed opening-only confirmation rule over a much larger sample.

Opening rule under test
-----------------------
09:15 FULL alignment:
  RSI > 50
  EMA3 > 50
  WMA21 > 50
  RSI > EMA3 > WMA21

=> OPENING_ALIGNMENT

09:20:
  RSI > WMA21
  => OPENING_HOLDING

  RSI <= WMA21
  => OPENING_REJECTED_0920

09:25:
  RSI > WMA21
  => OPENING_BULLISH_CONFIRMED

  RSI <= WMA21
  => OPENING_REJECTED_0925

No gap threshold is used.
Gap measurements remain diagnostic context only.

Run tests
---------
python -m pytest tests/test_validate_hilega_milega_opening_120_session_v2_1.py -v

Run 120 trading sessions
------------------------
python scripts/validate_hilega_milega_opening_120_session_v2_1.py \
  --end-date 2026-09-21 \
  --trading-sessions 120 \
  --calendar-lookback-days 190 \
  --intraday-date 2026-09-21

Output CSV
----------
data/historical-evidence/branch-c-opening-120-session-v2-1.csv

Paste back
----------
=== SUMMARY ===
plus the printed opening-alignment rows.
