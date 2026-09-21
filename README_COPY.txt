CONTROL FAILURE FORWARD PATH / EXIT OPPORTUNITY V6.12
======================================================

Purpose
-------
Finish Branch A before deciding whether to move this control-failure idea
into an options-premium backtest.

V6.12 does NOT change the entry model.

It analyzes the exact next-30-minute 1-minute price path after the
chronologically unseen V6.11 Variant-A candidates.

Primary question
----------------
Are the entries actually finding useful moves, but fixed +15m/+30m exits are
giving back too much of the favorable excursion?

Input
-----
data/historical-evidence/control-failure-forward-outcome-v6-11/
  forward-outcome-scored-candidates-v6-11.csv

The V6.11 score was learned chronologically from PRIOR sessions only.

Selection
---------
Variant A only.

Rank groups are calculated LOCALLY inside each unseen test session:

  ALL_PRIMARY_A
  TOP5_FOLD
  TOP10_FOLD
  TOP20_FOLD
  BOTTOM50_FOLD

This avoids comparing raw score magnitudes across different historical folds.

Exactness
---------
For every candidate V6.12 requires:

  trigger minute
  trigger+1
  trigger+2
  ...
  trigger+30

All must exist exactly.

No nearest timestamp.
No interpolation.
No shortened path.

Candidates lacking any exact minute are written to the errors CSV.

Metrics
-------
Full 30-minute path:

  MFE30
  MAE30
  time to MFE
  time to MAE

  did MFE happen before MAE?
  did MAE happen before MFE?

  adverse excursion before MFE
  favorable excursion before MAE

  MFE / MAE within:
    0-5m
    0-10m
    0-15m
    0-20m
    0-30m

  giveback:
    MFE -> +15m
    MFE -> +30m

  actual +15m
  actual +30m

No exit threshold is selected.

Test
----
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest   tests/test_validate_control_failure_forward_path_v6_12.py -v

Run
---
V6.11 must already have completed.

python scripts/validate_control_failure_forward_path_v6_12.py

Outputs
-------
data/historical-evidence/control-failure-forward-path-v6-12/

  forward-path-candidates-v6-12.csv
  forward-path-summary-v6-12.csv
  forward-path-errors-v6-12.csv
  forward-path-summary-v6-12.json

Main console section
--------------------
=== FORWARD PATH / EXIT OPPORTUNITY ===

What matters most
-----------------
For TOP10_FOLD:

1. median MFE30
2. median MAE30
3. median time-to-MFE
4. median adverse-before-MFE
5. MFE-before-MAE %
6. MFE giveback by +15/+30
7. comparison with BOTTOM50_FOLD

Potentially interesting pattern:
  strong MFE
  modest adverse-before-MFE
  relatively early time-to-MFE
  substantial giveback by fixed +30m

That would suggest entry may contain usable opportunity but exit management
needs work.

Unfavorable pattern:
  MFE only after large adverse excursion
  MAE commonly occurs before MFE
  TOP10 path looks similar to BOTTOM50

That would argue for pausing/stopping this control-failure branch rather than
adding more fitted entry features.
