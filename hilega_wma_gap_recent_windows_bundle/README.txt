Hilega WMA-gap recent 30/60/90-session report
================================================

This report reads the completed candidate-entry lifecycle evidence produced by
analyze_hilega_wma_gap_capture_failures.py.  It produces the same metrics for
three cumulative recent windows ending on the latest available session:

* LAST_30_SESSIONS
* LAST_60_SESSIONS
* LAST_90_SESSIONS

Trading sessions, rather than calendar days, are used so every window has the
declared number of market observations.  Exact start/end dates are printed and
stored in the report.

Prerequisite
------------

  PYTHONPATH=backend:. python \
    scripts/analyze_hilega_wma_gap_capture_failures.py

Install and run
---------------

  python hilega_wma_gap_recent_windows_bundle/install.py

  PYTHONPATH=backend:. python \
    scripts/report_hilega_wma_gap_recent_windows.py

Outputs
-------

  data/historical-evidence/hilega-wma-gap-recent-windows-v1/

  headline.csv
      Overall, bullish and bearish capture/giveback for each window.

  loss-groups.csv
      Immediate, early-reversal, late-giveback, same-exit-candle and other
      accepted losses for each direction/window.

  signal-periods.csv
      Opening, midday and afternoon performance.

  same-exit-candle.csv
      Same-exit-5m-candle results by window and direction.

  opposite-signals.csv
      Results separated by whether an opposite signal appeared within 10m.

  report.json
      Complete structured report with exact window dates.

Safety
------

Research only. No strategy, service, audit, order, paper order, quantity or
environment gate is changed.
