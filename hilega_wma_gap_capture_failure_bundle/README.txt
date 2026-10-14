Hilega WMA-gap capture and failure analysis
===========================================

This is the second-stage diagnostic for the ordered Hilega candidate.  It uses
the output of analyze_hilega_wma_gap_clear_losses.py and recomputes every
accepted trade from the actual delayed candidate entry through the canonical
completed exit close.

It answers:

* How many gross winning points did the candidate produce?
* How much of each winning trade's maximum favourable excursion was captured?
* How many points were given back before exit?
* Which losses failed immediately, reversed before T+5, or gave back profit
  after T+5?
* How do bullish and bearish results differ?
* What happened to trades entered inside their own exit-labelled 5m candle?
* Did a new opposite canonical signal appear while the trade was active?
* Are the results stable in all three chronological development blocks?

All MFE and MAE values use completed one-minute closes.  This matches the
candidate's completed-close entry and avoids unknown intrabar high/low order.

Prerequisite
------------

Run the clear loss diagnostic first:

  PYTHONPATH=backend:. python \
    scripts/analyze_hilega_wma_gap_clear_losses.py

Install and run
---------------

  python hilega_wma_gap_capture_failure_bundle/install.py

  PYTHONPATH=backend:. python \
    scripts/analyze_hilega_wma_gap_capture_failures.py

Output
------

  data/historical-evidence/hilega-wma-gap-capture-failures-490-v1/

  capture-trade-view.csv
  winner-capture-summary.csv
  loss-classification-summary.csv
  failure-group-trades.csv
  same-exit-candle-summary.csv
  opposite-signal-summary.csv
  report.json

Definitions
-----------

Candidate MFE
    Best directional completed-close profit after candidate entry.

Candidate MAE
    Worst directional completed-close movement after candidate entry.

Winner giveback
    candidate MFE - captured positive exit points.

Weighted capture ratio
    sum(captured positive points) / sum(candidate MFE for those winners).

Failure groups
    SAME_EXIT_5M_CANDLE
    IMMEDIATE_FAILURE_THROUGH_T5
    EARLY_REVERSAL_BY_T5
    LATE_GIVEBACK_AFTER_T5
    RECOVERED_AFTER_T5_THEN_LOST
    OTHER_ACCEPTED_LOSS

Safety
------

Research only.  No live strategy, service, audit, order, paper order, quantity
or environment gate is changed.
