B FAMILY — V40 FROZEN V38_CAP50 HISTORICAL VALIDATION
===========================================================

Current frozen development winner:
V38_CAP50

V40 applies that rule unchanged to the separate canonical 180-session block:

2025-12-12 through 2026-09-08

Important:
This block is date-separated from the 18-event V38 tuning population, but it is
not globally pristine because earlier B-family research used it. Treat V40 as
historical validation / stress evidence.

V40 does NOT tune parameters.

Frozen:
- V35 primary W1 AGE10
- V37 recovery/rebreak structure
- rescue cap = +50 points

Reports:
- number of sessions
- B events
- +20 events
- RUNNER_STRENGTHENING events
- baseline vs V38 total points
- delta vs baseline
- max drawdown
- +30/+40/+50/+75/+100 preservation
- later new MFE
- primary/rescue/fallback counts

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_v38_cap50_validation_v40.py \
  | tee /tmp/b-family-v38-cap50-validation-v40.txt

Paste the complete V40 output back.
