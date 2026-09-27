B FAMILY — CANONICAL INDEPENDENT VALIDATION V6.1
===================================================

This replaces the failed hand-reconstructed V6 detector.

It imports the repository's canonical:
  scripts/midpoint_vwap_60_session_setup_family_validation_v1_1.py

and directly reuses:
  family_b_for_event()
  measure_event()

Run:
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_canonical_independent_validation_v6_1.py \
  | tee /tmp/b-family-canonical-independent-validation-v6-1.txt

Required parity:
  latest60 canonical B = 18
  known frozen B = 18
  exact date/direction/entry timestamp match

Only then are older events reported.

Outputs:
data/historical-evidence/hilega-pcr-oi-support-research-v1/
  b-family-canonical-independent-validation-v6-1/
    b-family-canonical-parity-v6-1.csv
    b-family-canonical-older-events-v6-1.csv
    b-family-canonical-independent-summary-v6-1.txt

Research only. No runtime/execution changes.
