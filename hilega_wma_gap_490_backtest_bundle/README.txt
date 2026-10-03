HILEGA ORDERED WMA + GAP 490-SESSION BACKTEST
==============================================

This research-only bundle evaluates the exact candidate selected from the
September 30 and October 1 investigation:

  canonical directional Hilega signal
      -> directional WMA21-of-RSI9 change reaches 0.75 (ARM only)
      -> on a later consecutive completed 1-minute candle, WMA remains >= 0.75
         and the directional EMA3-WMA21 gap expands
      -> candidate entry at that completed 1-minute close
      -> unchanged canonical exit

Bullish gap: EMA3(RSI9) - WMA21(RSI9)
Bearish gap: WMA21(RSI9) - EMA3(RSI9)

The crossing/arming candle cannot also confirm the gap. Failed minute pairs may
re-arm inside the existing T+10 observation window.

Prerequisites
-------------

The repository must already contain:

  scripts/validate_hilega_wma_delayed_confirmation.py
  data/historical-evidence/hilega-alignment-points-490-v1/
    trade-alignment-points.csv
  data/historical-evidence/hilega-milega-underlying-cache-v1/

Install
-------

  cd ~/RB-ITOS-AI
  source .venv/bin/activate
  unzip -o hilega_wma_gap_490_backtest_bundle_v1.zip
  python hilega_wma_gap_490_backtest_bundle/install.py

Run
---

  PYTHONPATH=backend:. python \
    scripts/backtest_hilega_wma_gap_490.py

Outputs
-------

  data/historical-evidence/hilega-wma-gap-490-v1/
    report.json
    trade-results.csv
    confirmation-attempts.csv

The report separates bullish and bearish outcomes and includes canonical,
first-touch and ordered-WMA-gap policies; accepted/denied winners and losses;
entry-delay cost; +20 and frozen top-decile moves destroyed; chronological
development blocks; and the already-observed ten-session forward block.

Evidence contract
-----------------

The 480 historical sessions and existing ten forward sessions have already
been inspected, so all 490 are development/observed evidence. They are not a
new untouched OOS cohort. Future sessions remain the next untouched
confirmation cohort.

Safety
------

No live strategy, configuration, service, audit, order, paper order or
quantity is changed.

