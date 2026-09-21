Branch C V1.6 — Bullish / Strong Bullish

BULLISH:
1. RSI9 crosses EMA3 upward.
2. Later RSI9 crosses WMA21 upward.
3. RSI9 > 50 on that RSI/WMA crossover candle.

STRONG BULLISH:
- Bullish already active.
- RSI9 > WMA21 and EMA3 > WMA21.
- If true on same bullish candle: strong_delay=0m.
- If EMA3 gets above WMA21 later: strong_time is recorded with delay.

No maximum sequence duration.

Suggested run:
python -m pytest tests/test_validate_hilega_milega_bullish_strong_v1_6.py -v

python scripts/validate_hilega_milega_bullish_strong_v1_6.py \
  --session-date 2026-09-15 \
  --session-date 2026-09-16 \
  --session-date 2026-09-17 \
  --session-date 2026-09-18 \
  --session-date 2026-09-21 \
  --intraday-date 2026-09-21

Paste:
=== BRANCH C BULLISH / STRONG BULLISH ===
