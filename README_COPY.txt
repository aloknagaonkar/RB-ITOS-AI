Branch C V2.4 — Same-candle RSI/WMA + EMA/WMA crossover validation

This version formalizes one important rule:

After RSI↑EMA3 has armed the setup, RSI↑WMA21 and EMA3↑WMA21 may happen
on the SAME 5-minute candle.

That candle is allowed to transition directly:

ARMED
  -> ACTIVE_SETUP
  -> BULLISH        (if RSI > 50)
  -> STRONG_BULLISH (if EMA3 > WMA21)

No extra 5-minute wait is required.

Three supported patterns
------------------------
A. RSI↑WMA first; EMA3 crosses above WMA later.
B. RSI↑WMA and EMA3↑WMA on the same candle.
C. EMA3 is already above WMA when RSI↑WMA occurs.

Sequence context is preserved: without the earlier RSI↑EMA3 arming event,
a same-candle RSI/WMA + EMA/WMA crossover does not create a new setup.

Run
---
python -m pytest tests/test_validate_hilega_milega_same_candle_cross_v2_4.py -v

python scripts/validate_hilega_milega_same_candle_cross_v2_4.py

Expected
--------
PASS: same-candle RSI↑WMA + EMA3↑WMA is accepted immediately.
