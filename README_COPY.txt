Branch C V1.8 — Bullish progression manual validation

Progression under observation
-----------------------------
ACTIVE_SETUP:
  RSI > WMA21 after an RSI↑WMA event that followed RSI↑EMA.

BULLISH:
  RSI > WMA21 AND RSI > 50.

STRONG_BULLISH:
  RSI > WMA21 AND EMA3 > WMA21 AND RSI > 50.

FULL_BULLISH_ALIGNMENT:
  RSI > 50
  EMA3 > 50
  WMA21 > 50
  RSI > EMA3 > WMA21

Additional milestone timestamps
-------------------------------
RSI↑50
EMA3↑50
WMA21↑50
EMA3↑WMA

Invalidation is still logged as RSI↓WMA for manual review only.
No new profitability rule is introduced.

Run tests
---------
python -m pytest tests/test_validate_hilega_milega_bullish_progression_v1_8.py -v

Run 5-day report
----------------
python scripts/validate_hilega_milega_bullish_progression_v1_8.py \
  --session-date 2026-09-15 \
  --session-date 2026-09-16 \
  --session-date 2026-09-17 \
  --session-date 2026-09-18 \
  --session-date 2026-09-21 \
  --intraday-date 2026-09-21

CSV
---
data/historical-evidence/branch-c-bullish-progression-v1-8.csv

Paste back:
=== BRANCH C BULLISH PROGRESSION V1.8 ===
