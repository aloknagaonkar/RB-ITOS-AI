HILEGA WMA ONE-MINUTE PERSISTENCE RESEARCH
==========================================

Purpose
-------
Compare the existing first-touch WMA confirmation with a stricter, causal
one-minute persistence confirmation.  This is research-only and does not
modify the live Hilega strategy.

Folder structure installed
--------------------------

  scripts/analyze_hilega_wma_one_minute_persistence.py
  tests/test_analyze_hilega_wma_one_minute_persistence.py

Prerequisite
------------
Run the existing two-day delayed-confirmation validator first.  Its V2 output
must contain:

  data/historical-evidence/
    hilega-wma-delayed-confirmation-2026-09-30-2026-10-01-v2/
      trade-validation.csv
      minute-by-minute-wma.csv

Install and run
---------------

  cd ~/RB-ITOS-AI
  source .venv/bin/activate

  python hilega_wma_one_minute_persistence_bundle/install.py

  PYTHONPATH=backend:. python \
    scripts/analyze_hilega_wma_one_minute_persistence.py

Rule
----
1. The unchanged canonical Hilega strategy must already have emitted a signal.
2. The first completed one-minute observation with directional WMA change
   >= 0.75 arms the setup; it does not enter.
3. A later immediately consecutive completed minute confirms only when:
   - directional WMA change remains >= 0.75;
   - RSI/EMA/WMA are fully aligned in the trade direction;
   - EMA continues in the trade direction versus the armed minute; and
   - the directional EMA-WMA gap does not contract versus the armed minute.
4. Failed pairs may re-arm while the original T+10 observation window remains
   open.  There is no entry after that existing window.
5. Candidate entry valuation is the actual close of the persistence candle.

Outputs
-------

  data/historical-evidence/
    hilega-wma-one-minute-persistence-2026-09-30-2026-10-01-v1/
      report.json
      trade-comparison.csv
      persistence-attempts.csv

Safety
------
No live strategy, service, audit, order, paper-order or quantity is changed.

