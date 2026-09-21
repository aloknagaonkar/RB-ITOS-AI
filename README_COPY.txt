CONTROL FAILURE CONTEXT GENERALIZATION V6.9
===========================================

Purpose
-------
Test whether V6.8's context relationship generalizes to an unseen trading
session rather than merely describing the same sessions used for discovery.

Population
----------
All 28 currently available sessions from the V6.8 enriched candidate file.

Validation
----------
Leave-one-session-out (LOSO):

  train/discover on 27 sessions
  score the 1 held-out session
  repeat for all 28 sessions

The held-out session's NEAR_MOVE/NON_MOVE labels are NEVER used to choose
features or construct the score for that fold.

Direction normalization
-----------------------
Bullish and bearish candidates are mapped into common research variables:

  opposite_spot_pressure_5m/10m/15m
  opposite_oi_pressure_5m/10m/15m
  opposite_pcr_pressure_5m/10m/15m
  opposite_oi_velocity_5m
  opposite_oi_acceleration_5m

plus:
  failure_count_5m
  max_consecutive_failure_count
  failure_earliness
  decay_count_5m

Example:
  bullish candidate + prior bearish 15m spot trend -> positive
  bearish candidate + prior bullish 15m spot trend -> positive

Fold feature discovery
----------------------
Within each 27-session training fold:

- compare NEAR_MOVE vs NON_MOVE medians
- scale separation by pooled MAD
- rank features by absolute training-only robust separation
- use the top 6 features

No held-out-session labels participate.

Scoring
-------
Each held-out row receives a score based on whether its normalized features
are closer to the TRAINING NEAR_MOVE medians than to TRAINING NON_MOVE
medians.

Evaluation
----------
Threshold-free:
  pooled leave-one-session-out AUC
  median per-fold AUC

Fixed rank cuts:
  top 5%
  top 10%
  top 20%

For each cut:
  lift
  recall
  precision

These rank cuts are evaluation diagnostics only and are NOT live thresholds.

Interpretation
--------------
AUC:
  0.50 = no ranking separation
  >0.50 = context learned from other sessions tends to rank held-out
          NEAR_MOVE candidates above held-out NON_MOVE candidates

Lift:
  >1.0 = the top-ranked subset contains more genuine near-move events than
         the held-out/base population rate

No trading rule or profitability claim is made by V6.9.

Test
----
cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest   tests/test_validate_control_failure_context_generalization_v6_9.py -v

Run
---
V6.8 must already have completed.

python scripts/validate_control_failure_context_generalization_v6_9.py

Input
-----
data/historical-evidence/control-failure-context-discrimination-v6-8/
  context-enriched-candidates-v6-8.csv

Outputs
-------
data/historical-evidence/control-failure-context-generalization-v6-9/

  loso-fold-results-v6-9.csv
  loso-scored-candidates-v6-9.csv
  loso-summary-v6-9.csv
  loso-summary-v6-9.json

Main console section
--------------------
=== LEAVE-ONE-SESSION-OUT GENERALIZATION ===

What we want to see
-------------------
We are NOT looking for a perfect AUC.

The useful result would be:
- pooled LOSO AUC meaningfully above 0.50
- positive lift at top 5% / 10%
- similar behavior across more than only a handful of folds

If V6.9 collapses toward AUC ~0.50 and lift ~1.0, the apparent V6.8 context
relationship is not generalizing well enough and should not become a strategy.
