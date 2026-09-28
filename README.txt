B FAMILY — V36 SECOND-STAGE RESCUE EXIT OPTIMIZATION
======================================================

Keeps V35_W1_AGE10 as the primary exit.

Tunes a secondary rescue exit for events V35 leaves as fallbacks:
- timeout: 10 / 15 / 20 / 30 / 45 minutes
- confirmation: none or directional futures-VWAP still weak

Reports:
- total points
- delta vs V34.2 baseline
- delta vs V29
- delta vs V35
- mean / median / worst / best / max drawdown
- +30/+40/+50/+75/+100 chase success
- later-new-MFE
- primary / rescue / fallback counts

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_second_stage_rescue_v36.py \
  | tee /tmp/b-family-second-stage-rescue-v36.txt

Paste the complete output back.
