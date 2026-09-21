Branch C V1.7 — Five-day manual validation

Purpose
-------
Reconstruct the bullish state machine for manual chart validation.
This is NOT a profitability/backtest filter.

Current state rules
-------------------
NEUTRAL -> ARMED:
  RSI9 crosses EMA3 upward.

ARMED -> BULLISH:
  RSI9 later crosses WMA21 upward AND RSI9 > 50.

BULLISH -> STRONG:
  EMA3 > WMA21 while bullish remains active.

BULLISH -> NEUTRAL:
  RSI9 crosses below WMA21.

During an active BULLISH state:
  another RSI↑EMA or RSI↑WMA event is logged as CONTINUATION,
  not as a new bullish start.

Manual validation dates
-----------------------
2026-09-15
2026-09-16
2026-09-17
2026-09-18
2026-09-21

Run tests
---------
python -m pytest tests/test_validate_hilega_milega_manual_validation_v1_7.py -v

Run report
----------
python scripts/validate_hilega_milega_manual_validation_v1_7.py \
  --session-date 2026-09-15 \
  --session-date 2026-09-16 \
  --session-date 2026-09-17 \
  --session-date 2026-09-18 \
  --session-date 2026-09-21 \
  --intraday-date 2026-09-21

CSV output
----------
data/historical-evidence/branch-c-manual-validation-v1-7.csv

Fill:
manual_label = CORRECT / FALSE / LATE / EARLY / CONTINUATION / MISSED
manual_notes = your chart observation

Paste back:
=== BRANCH C FIVE-DAY MANUAL VALIDATION ===
