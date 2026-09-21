BRANCH C — HILEGA-MILEGA — BULLISH TODAY V1
============================================

Only bullish validation for 2026-09-21.

Frozen bullish rule
-------------------
RSI(9) crosses ABOVE EMA3(RSI9)
AND
RSI(9) > WMA21(RSI9)
AND
EMA3(RSI9) > WMA21(RSI9)

No RSI-50 condition.
No bearish condition.
No OI/PCR.
No extra filters.

Output
------
The console prints exact 5-minute candle timings:

  HH:MM -> HH:MM
  close
  RSI9
  EMA3(RSI)
  WMA21(RSI)

so each occurrence can be checked directly on TradingView.

Test
----
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest   tests/test_validate_hilega_milega_bullish_today_v1.py -v

Basic run
---------
python scripts/validate_hilega_milega_bullish_today_v1.py   --session-date 2026-09-21

Default target file:
data/historical-evidence/historical-oi-build/2026-09-21/positioning.json

If today's positioning.json is elsewhere
-----------------------------------------
python scripts/validate_hilega_milega_bullish_today_v1.py   --session-date 2026-09-21   --positioning /exact/path/to/positioning.json

Recommended TradingView-accurate warm-up
-----------------------------------------
RSI and WMA need prior bars. If the previous trading session's positioning
file exists, supply it:

python scripts/validate_hilega_milega_bullish_today_v1.py   --session-date 2026-09-21   --warmup-positioning data/historical-evidence/historical-oi-build/2026-09-18/positioning.json

If more historical warm-up is available, --warmup-positioning may be repeated
oldest first.

Without prior-session warm-up, the script labels the run SAME_SESSION_ONLY
and warns that early-morning TradingView values may differ.

Outputs
-------
data/historical-evidence/branch-c-hilega-milega-bullish-today-v1/
  bullish-signals-today-v1.csv
  bullish-signals-today-v1.json

After running, paste the console section:
=== BULLISH CANDLE TIMINGS TO VALIDATE ON CHART ===
