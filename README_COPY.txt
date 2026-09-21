CONTROL FAILURE CHRONOLOGICAL WALK-FORWARD V6.10
================================================

Purpose
-------
Remove the remaining look-forward concern from V6.9.

V6.9:
  train on all other sessions, including later dates.

V6.10:
  train only on sessions chronologically BEFORE the test session.

Frozen walk-forward design
--------------------------
All 28 available sessions remain in chronological order.

Minimum prior history:
  8 sessions

Therefore:
  first 8 sessions = history warm-up only
  remaining 20 sessions = chronological unseen test sessions

Example:
  train sessions 1..8
  test session 9

  train sessions 1..9
  test session 10

  ...

  train sessions 1..27
  test session 28

No future session can affect an earlier test session.

Primary research population
---------------------------
Variant A is PRIMARY.

Variants B/C/D/E are still reported for comparison only.

Direction-normalized features
-----------------------------
Same frozen V6.9 representation:

  opposite_spot_pressure_5m/10m/15m
  opposite_oi_pressure_5m/10m/15m
  opposite_pcr_pressure_5m/10m/15m
  opposite_oi_velocity_5m
  opposite_oi_acceleration_5m

  failure_count_5m
  max_consecutive_failure_count
  failure_earliness
  decay_count_5m

Feature discovery
-----------------
For EACH chronological fold:

- use only earlier sessions
- compare training NEAR_MOVE vs NON_MOVE
- rank by training-only robust separation
- select top 6 eligible features
- score the next unseen future session

Held-out/test labels never select features.

Early-fold safety
-----------------
A feature must have at least:
  5 training NEAR_MOVE values
  30 training NON_MOVE values

Otherwise it is not eligible.

If a fold has no eligible features, V6.10 reports that rather than using
future information or fabricating fallback features.

Evaluation
----------
Ranking/generalization:
  pooled chronological walk-forward AUC
  median per-fold AUC

Fixed rank diagnostics:
  top 5%
  top 10%
  top 20%

For EACH ranked subset, V6.10 ALSO reports actual directional price outcome:

  median/mean +5m
  median/mean +10m
  median/mean +15m
  median/mean +30m

  hit rates
  median MFE30
  median MAE30

This is the bridge between:
  "Does it rank known transitions?"
and
  "Do high-ranked unseen candidates have better forward price behavior?"

Important
---------
No rank cut is selected as a live threshold.
No CE/PE premium profitability is claimed here.
No threshold tuning is performed.

Test
----
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest   tests/test_validate_control_failure_chronological_walkforward_v6_10.py -v

Run
---
V6.8 must already have completed.

python scripts/validate_control_failure_chronological_walkforward_v6_10.py

Default:
  minimum prior sessions = 8

Output
------
data/historical-evidence/control-failure-chronological-walkforward-v6-10/

  walkforward-fold-results-v6-10.csv
  walkforward-scored-candidates-v6-10.csv
  walkforward-summary-v6-10.csv
  walkforward-summary-v6-10.json

Main console section
--------------------
=== CHRONOLOGICAL WALK-FORWARD GENERALIZATION ===

What matters most
-----------------
For PRIMARY Variant A:

1. Is chronological AUC still > 0.50?
2. Does top-10% lift remain > 1?
3. Do top-ranked unseen candidates show better +15m/+30m median directional
   movement than the full candidate population?
4. Are +15m/+30m hit rates above the ~50% noise level?
5. Is MFE/MAE behavior improving enough to justify an option-premium backtest?

If V6.10 collapses toward:
  AUC ~0.50
  lift ~1.0
  forward hit rates ~50%
then V6.9 was not robust enough.

If V6.10 survives chronologically, the next step is to freeze the candidate
signal and test actual CE/PE option premium economics including costs.
