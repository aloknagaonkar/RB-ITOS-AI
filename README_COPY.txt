OI PRICE FAILURE TRANSITION V4
==============================

Research-only analyzer centered on the dated 5-minute candles around the event.

Copy into ~/RB-ITOS-AI preserving folders:

scripts/analyze_oi_price_failure_transition_v4.py
tests/test_analyze_oi_price_failure_transition_v4.py

Test
----
cd ~/RB-ITOS-AI
source .venv/bin/activate
python -m pytest tests/test_analyze_oi_price_failure_transition_v4.py -v

Run
---
python scripts/analyze_oi_price_failure_transition_v4.py \
  --date 2026-09-21 \
  --breadth-input data/live-observation/analysis/2026-09-21-fixed-event-oi-pm2-strike-breadth-summary-v3.csv \
  --focus-times 10:35 10:40

Candle semantics
----------------
checkpoint 2026-09-21 10:35 = completed 5m candle 2026-09-21 10:30 -> 10:35
checkpoint 2026-09-21 10:40 = completed 5m candle 2026-09-21 10:35 -> 10:40

Research metrics
----------------
- exact session date and candle start/end timestamp
- spot and 5m spot change
- aggregate OI imbalance
- imbalance velocity
- imbalance acceleration
- bullish/bearish strike breadth
- ATM strike state
- OI direction vs actual price response
- transition phase:
  BEARISH_ACCELERATING
  BEARISH_FADING
  BEARISH_FADING_REVERSAL
  PRICE_OI_DIVERGENCE
  EARLY_BULL_TRANSITION
  BROAD_BULLISH_CONFIRMATION

No strategy or execution logic is modified.
