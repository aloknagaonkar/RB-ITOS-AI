BRANCH C — HILEGA-MILEGA — BULLISH TRANSITION AUDIT V1.2
=========================================================

Purpose
-------
Do NOT impose a combined bullish timing rule yet.
Print each upward crossover event independently so the exact sequence can be checked on TradingView.

Events audited
--------------
1. RSI9 crosses EMA3(RSI9) upward
2. RSI9 crosses WMA21(RSI9) upward
3. EMA3(RSI9) crosses WMA21(RSI9) upward

For each transition candle, also print whether RSI9 / EMA3 / WMA21 are each sloping upward.

No bearish rule.
No OI/PCR.
No RSI-50 filter.
No fixed multi-candle timing window.

Test
----
cd ~/RB-ITOS-AI
source .venv/bin/activate
python -m pytest tests/test_validate_hilega_milega_bullish_transition_audit_v1_2.py -v

Run
---
python scripts/validate_hilega_milega_bullish_transition_audit_v1_2.py \
  --session-date 2026-09-21 \
  --warmup-date 2026-09-17 \
  --warmup-date 2026-09-18

Paste this console section back:
=== BULLISH TRANSITION SEQUENCE TO VALIDATE ON CHART ===
