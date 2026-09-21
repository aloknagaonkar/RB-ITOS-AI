BRANCH C — HILEGA-MILEGA — PREVIOUS DATES BULLISH V1.3
========================================================

Frozen bullish sequence
-----------------------
1. RSI9 crosses EMA3(RSI9) upward first.
2. AFTER that, wait for both:
   - RSI9 crosses WMA21(RSI9) upward
   - EMA3(RSI9) crosses WMA21(RSI9) upward
3. The final required WMA crossover is the bullish confirmation candle.
4. On confirmation, RSI9, EMA3 and WMA21 must all slope upward.

IMPORTANT
---------
There is NO maximum sequence duration.

A sequence taking 10, 15, 20, 25, 30 minutes or longer is not rejected
because of duration.

The script records:
- RSI/EMA crossover time
- RSI/WMA crossover time
- EMA/WMA crossover time
- confirmation time
- actual sequence duration in minutes
- RSI9 / EMA3 / WMA21 values

WMA crossings that happened BEFORE RSI9 crossed EMA3 are not counted toward
that sequence because the intended order starts with RSI9 crossing EMA3.

Suggested first historical validation
-------------------------------------
2026-09-14
2026-09-15
2026-09-16
2026-09-17
2026-09-18

Run tests
---------
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest   tests/test_validate_hilega_milega_bullish_previous_dates_v1_3.py -v

Run previous five sessions
--------------------------
python scripts/validate_hilega_milega_bullish_previous_dates_v1_3.py   --session-date 2026-09-14   --session-date 2026-09-15   --session-date 2026-09-16   --session-date 2026-09-17   --session-date 2026-09-18

The script fetches earlier calendar days automatically for indicator warm-up.

Paste this console section back into ChatGPT:
=== BRANCH C BULLISH CONFIRMATIONS — PREVIOUS DATES ===

Then visually validate the reported CONFIRM candles on TradingView.
