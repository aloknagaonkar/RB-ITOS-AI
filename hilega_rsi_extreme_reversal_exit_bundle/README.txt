HILEGA RSI EXTREME-ZONE REVERSAL EXIT RESEARCH

This test does NOT exit when RSI first becomes extreme. It arms the exit and
waits for momentum to leave the extreme zone on a later completed 5m close.

Bullish
  Arm: RSI >= 70
  Exit: a later completed 5m RSI < 70

Bearish
  Arm: RSI <= 30
  Exit: a later completed 5m RSI > 30

Policies
  RSI9 reversal
  RSI9 reversal after +20 proof
  RSI14 reversal
  RSI14 reversal after +20 proof
  Existing RSI9/WMA21 exit control

Install and run
  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python hilega_rsi_extreme_reversal_exit_bundle/install.py

  PYTHONPATH=backend:. python \
    scripts/research_hilega_rsi_extreme_reversal_exits.py

Output
  data/historical-evidence/hilega-rsi-extreme-reversal-exits-490-v1/

The output includes all 490 sessions, development blocks, observed forward,
recent/prior/earlier 30 sessions, bullish/bearish separation, and September 30
and October 1 trade-level examples.

Research only. Live strategy, services, audits, orders and quantity remain
unchanged.
