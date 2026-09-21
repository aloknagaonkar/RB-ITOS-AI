Branch C V1.9 — 30-session robustness audit

Purpose
-------
Test two unresolved state rules over 30 trading sessions without changing
the normal intraday progression logic.

Rule A — Opening alignment
--------------------------
09:15 full alignment:
  RSI > 50
  EMA3 > 50
  WMA21 > 50
  RSI > EMA3 > WMA21

=> OPENING_ALIGNMENT only.

Next 5m candle:
  if RSI remains > WMA21:
      OPENING_BULLISH_CONFIRMED
  else:
      OPENING_ALIGNMENT_FAILED

This intentionally adds +5m confirmation only to opening-alignment cases.

Rule B — Two-stage invalidation
-------------------------------
First RSI cross below WMA21:
  WEAKENING

Next candle:
  if RSI still < WMA21:
      BULLISH_END_CONFIRMED
  if RSI recovered > WMA21:
      WEAKENING_RECOVERY / CONTINUATION

Normal progression retained
---------------------------
ACTIVE_SETUP:
  RSI↑EMA -> RSI↑WMA

BULLISH:
  RSI > WMA21 and RSI > 50

STRONG_BULLISH:
  RSI > WMA21, EMA3 > WMA21, RSI > 50

FULL_BULLISH_ALIGNMENT:
  RSI > 50, EMA3 > 50, WMA21 > 50, RSI > EMA3 > WMA21

Run tests
---------
python -m pytest tests/test_validate_hilega_milega_30_session_robustness_v1_9.py -v

Run 30 trading sessions ending 2026-09-21
-----------------------------------------
python scripts/validate_hilega_milega_30_session_robustness_v1_9.py \
  --end-date 2026-09-21 \
  --trading-sessions 30 \
  --calendar-lookback-days 50 \
  --intraday-date 2026-09-21

Output CSV:
data/historical-evidence/branch-c-30-session-robustness-v1-9.csv

Paste back:
=== SUMMARY ===
and the sections for 2026-09-17, 2026-09-18, 2026-09-21.
