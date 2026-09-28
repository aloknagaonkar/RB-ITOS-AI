B FAMILY — V34 RECOVERY-ATTEMPT DETERIORATION + POINTS SCORECARD
=================================================================

Purpose
-------
Study what happens after the BEST recovery attempt inside the DEGRADED state.

Also introduces a permanent point-accounting convention for future testing.

V34 measures:
- best recovery attempt
- subsequent gap expansion
- weakening after best attempt
- time from best attempt to recovery/invalidation
- recovered counterexamples

POINT ACCOUNTING
----------------
From V34 onward, every actual exit candidate should report:
- directional NIFTY points at exit
- total / mean / median
- improvement vs structural invalidation baseline
- improvement vs previous candidate
- runner preservation (+50/+75/+100)
- max drawdown where meaningful

This script itself does NOT create an exit rule, so recovered state transitions
are NOT counted as realized P&L.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_recovery_deterioration_points_v34.py \
  | tee /tmp/b-family-recovery-deterioration-points-v34.txt

Paste the complete V34 output back.
