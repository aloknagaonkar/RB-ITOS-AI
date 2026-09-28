MIDPOINT FAMILY E — V53

What this does:
- freezes Family E's entry definition
- validates mutually-exclusive B/E boundary ownership
- leaves Family B unchanged
- replays 2026-09-28 from the live audit
- does NOT modify live runtime
- does NOT enable Family E

Prerequisite:
scripts/midpoint_mature_boundary_robustness_v52_1.py must already exist.

Run:
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_family_e_v53_freeze_and_coordinator_validation.py

Then:
cat \
data/historical-evidence/hilega-pcr-oi-support-research-v1/\
midpoint-family-e-v53/summary-v53.txt

Expected 2026-09-28 bearish replay:
09:26 boundary should classify owner=E with
MATURE_DIRECTIONAL_VWAP_AT_BOUNDARY.

Do not enable E live from V53.
V54 is the next phase: shared B/E post-entry management parity.
