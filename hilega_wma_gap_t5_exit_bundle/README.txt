Hilega WMA-gap exact T+5 exit research
=======================================

This bundle tests an early-risk exit on top of the already-tested ordered
Hilega entry candidate:

  canonical signal -> WMA21 directional strength >= 0.75 -> next completed
  1m close keeps WMA >= 0.75 and expands the positive EMA3/WMA21 gap.

The entry sequence is not changed.  The canonical exit remains the control.
Each candidate may act once, only at the exact completed T+5 candle measured
from the delayed candidate entry.  There is no continuous monitoring after
T+5.

Policies
--------

CURRENT_EXIT_POLICY
    Existing canonical exit.

T5_PRICE_NONPOSITIVE
    Exit at T+5 when directional points from candidate entry are <= 0.

T5_PRICE_2_OF_4_WEAK
    Exit at T+5 when price progress is <= 0 and at least two components are
    weak: WMA21 strength below 0.75; directional EMA/WMA gap non-positive or
    contracting; EMA3 not continuing; RSI/EMA/WMA alignment false.

T5_PRICE_ALL_4_WEAK
    Exit only when price progress is <= 0 and all four components are weak.

Prerequisite
------------

The capture/failure analysis must already have been run:

  PYTHONPATH=backend:. python \
    scripts/analyze_hilega_wma_gap_capture_failures.py

Install and run
---------------

  python hilega_wma_gap_t5_exit_bundle/install.py

  PYTHONPATH=backend:. python \
    scripts/research_hilega_wma_gap_t5_exits.py

Output
------

  data/historical-evidence/hilega-wma-gap-t5-exits-490-v1/

  report.json
  headline.csv
  trade-policy-comparison.csv
  exit-trigger-details.csv
  daily-policy-summary.csv

The report is separated by bullish/bearish direction, three chronological
development blocks, observed-forward evidence, all 490 sessions, and three
non-overlapping recent 30-session blocks.

Preservation checks use every completed one-minute close between the delayed
candidate entry and T+5.  Therefore a +20 or top-decile move achieved at T+2
or T+4 is not incorrectly counted as destroyed.

Safety
------

Research only.  No live strategy, signal, service, audit, order, paper order,
quantity or environment gate is changed.
