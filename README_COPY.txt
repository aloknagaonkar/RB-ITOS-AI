CONTROL FAILURE FORWARD-OUTCOME GENERALIZATION V6.11
====================================================

Purpose
-------
Stop optimizing toward retrospective NEAR_MOVE labels and test the economic
question more directly:

Can causal pre-trigger context rank candidates that later produce better
directional price outcomes on chronologically unseen sessions?

Population
----------
Same 28 available sessions from V6.8.

Chronological validation
------------------------
Minimum prior history = 8 sessions.

train on prior sessions only
score next unseen future session
expand history by one session
repeat

No future session can affect an earlier test session.

Primary population
------------------
Variant A is PRIMARY.
Variants B/C/D/E are reported for comparison.

Frozen continuous training target
---------------------------------
No profitable-trade threshold is introduced.

training_target =
    (directional move +15m + directional move +30m) / 2

This remains continuous.

Direction-normalized causal features
------------------------------------
opposite_spot_pressure_5m/10m/15m
opposite_oi_pressure_5m/10m/15m
opposite_pcr_pressure_5m/10m/15m
opposite_oi_velocity_5m
opposite_oi_acceleration_5m
failure_count_5m
max_consecutive_failure_count
failure_earliness
decay_count_5m

For each training fold
----------------------
- compute Spearman relation between each feature and the frozen continuous
  forward-outcome target using TRAINING sessions only
- choose top 6 features by absolute training Spearman
- robust-center/scale from training only
- score the next unseen session

No test-session outcome participates in feature selection or scoring.

Evaluation
----------
Threshold-free:
  pooled score-vs-outcome Spearman
  median per-fold Spearman

Fixed rank diagnostics:
  top 5%
  top 10%
  top 20%
  top 50%

For each:
  median/mean +5m/+10m/+15m/+30m
  hit rates
  median MFE30
  median MAE30

Also:
  bottom 50% forward-return comparison

No rank cut is selected as a live threshold.

Test
----
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest   tests/test_validate_control_failure_forward_outcome_generalization_v6_11.py -v

Run
---
V6.8 must already have completed.

python scripts/validate_control_failure_forward_outcome_generalization_v6_11.py

Outputs
-------
data/historical-evidence/control-failure-forward-outcome-v6-11/

  forward-outcome-fold-results-v6-11.csv
  forward-outcome-scored-candidates-v6-11.csv
  forward-outcome-summary-v6-11.csv
  forward-outcome-summary-v6-11.json

Main console section
--------------------
=== CHRONOLOGICAL FORWARD-OUTCOME GENERALIZATION ===

What matters most for Variant A
-------------------------------
We want to see whether, on future unseen sessions:

- pooled score/outcome Spearman is positive
- top10 median +15m and +30m are positive
- top10 +15/+30 hit rates move meaningfully above 50%
- top10 MFE is materially larger than adverse excursion
- top10 outperforms the full population and bottom 50%

If those do not survive, this control-failure research branch should not be
pushed into an option-premium strategy merely by adding more fitted filters.
