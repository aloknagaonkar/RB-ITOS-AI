HILEGA RSI14 STRUCTURAL-CONFIRMATION EXIT RESEARCH

Sequence
  1. Trade reaches +20 proof.
  2. RSI14 enters directional extreme: bullish >=70, bearish <=30.
  3. RSI14 later leaves the extreme zone: warning only.
  4. The next completed 5m candle evaluates:
       - RSI14 continues against the trade.
       - Directional EMA3(RSI9)-WMA21(RSI9) gap contracts.
       - Directional WMA21(RSI9) slope weakens.
  5. Compare 2-of-3 and strict 3-of-3 confirmation.
  6. Cancel the warning if RSI returns extreme or the gap expands.

Install and run
  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  python hilega_rsi14_structural_confirmation_bundle/install.py

  PYTHONPATH=backend:. python \
    scripts/research_hilega_rsi14_structural_confirmation.py

Output
  data/historical-evidence/hilega-rsi14-structural-confirmation-490-v1/

Research only. No live strategy, audit, service, order, paper order or
quantity is changed.
