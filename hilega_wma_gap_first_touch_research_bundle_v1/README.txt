Hilega WMA-gap causal first-touch research V1

What changes
------------
1. The WMA-gap candle audit uses the completed canonical signal-bar snapshot
   as the causal comparison baseline on the first observed one-minute candle.
2. Gap expansion and EMA3 continuation therefore show real previous/current
   values on that first minute instead of ``None``.
3. WMA persistence remains WAIT on the first minute because persistence still
   requires a later one-minute observation.
4. A read-only research script compares three policies over frozen 490-session
   evidence and any separately published forward sessions:
   * CURRENT_TWO_MINUTE_PERSISTENCE
   * FIRST_TOUCH_GE_0_75
   * FIRST_TOUCH_GE_1_00

The two first-touch policies require all of these on the same completed minute:
canonical signal, WMA threshold, positive directional EMA3-WMA21 gap, expanding
gap, directional EMA3 continuation and RSI9/EMA3/WMA21 alignment. Entry remains
limited to T+10 and exit remains the unchanged canonical exit.

Install
-------
python hilega_wma_gap_first_touch_research_bundle_v1/install.py

Run analysis
------------
PYTHONPATH=backend:. python scripts/research_hilega_wma_gap_first_touch.py

Outputs
-------
data/historical-evidence/hilega-wma-gap-first-touch-v1/report.json
data/historical-evidence/hilega-wma-gap-first-touch-v1/headline.csv
data/historical-evidence/hilega-wma-gap-first-touch-v1/trade-comparison.csv

Safety
------
Research/UI audit only. It does not modify the live Hilega strategy, sandbox or
live orders, quantity, canonical lifecycle, canonical exit, or frozen evidence.
