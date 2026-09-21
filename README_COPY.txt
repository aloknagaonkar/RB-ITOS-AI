BRANCH C — HILEGA-MILEGA BULLISH V1.1
=====================================

Strict bullish rule on the same completed 5-minute candle:

Condition 1
-----------
RSI(9) crosses upward above EMA3(RSI9):
  prev RSI9 <= prev EMA3
  curr RSI9 > curr EMA3

Condition 2
-----------
Both RSI9 and EMA3(RSI9) cross upward above WMA21(RSI9):
  prev RSI9 <= prev WMA21
  curr RSI9 > curr WMA21
  prev EMA3 <= prev WMA21
  curr EMA3 > curr WMA21

Upward slope condition retained from the prior clarification:
  curr RSI9 > prev RSI9
  curr EMA3 > prev EMA3
  curr WMA21 > prev WMA21

No RSI-50 condition.
No bearish logic.
No OI/PCR.
No option logic.

The script fetches current-day Nifty 1-minute candles from the Upstox V3 intraday endpoint and historical 1-minute warm-up dates from the V3 historical endpoint, builds exact completed 5-minute bars, calculates RSI9 / EMA3(RSI9) / WMA21(RSI9), and prints exact chart candle timings.

TEST
----
cd ~/RB-ITOS-AI
source .venv/bin/activate
python -m pytest tests/test_validate_hilega_milega_bullish_today_v1_1.py -v

RUN FOR 2026-09-21
------------------
python scripts/validate_hilega_milega_bullish_today_v1_1.py \
  --session-date 2026-09-21 \
  --warmup-date 2026-09-17 \
  --warmup-date 2026-09-18

Paste the section:
  === STRICT BULLISH CANDLE TIMINGS TO VALIDATE ON CHART ===
