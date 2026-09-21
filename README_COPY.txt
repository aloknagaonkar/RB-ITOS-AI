Branch C V2.3 — RSI / EMA3 / WMA21 Candle-by-Candle Audit

Purpose
-------
Inspect exact indicator values for a bullish signal from bullish start
through bullish end.

Example: 29 May 2026, 09:35 -> 09:45
----------------------------------------
python scripts/validate_hilega_milega_indicator_audit_v2_3.py \
  --date 2026-05-29 \
  --start 09:35 \
  --end 09:45

All completed bullish signals on 29 May:
---------------------------------------
python scripts/validate_hilega_milega_indicator_audit_v2_3.py \
  --date 2026-05-29 \
  --all-signals

Output columns
--------------
TIME
CLOSE
RSI9
EMA3
WMA21
RSI-EMA3
RSI-WMA21
EMA3-WMA21
RSI>50
EMA3>WMA21
RSI>EMA3
RSI>WMA21

Generated CSV
-------------
data/historical-evidence/branch-c-indicator-audit-v2-3.csv

Tests
-----
python -m pytest tests/test_validate_hilega_milega_indicator_audit_v2_3.py -v
