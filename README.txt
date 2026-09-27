B FAMILY — UNTOUCHED HISTORICAL PILOT V21
===========================================

This runs the frozen Family-B detector on the five Jan-2025 sessions for which
underlying and futures/VWAP data have already been collected.

Inputs expected:
data/historical-evidence/b-v21-pilot-underlying-2025-01-13-to-17.csv
data/historical-evidence/b-v21-pilot-futures-vwap-2025-01-13-to-17.csv

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_untouched_historical_pilot_v21.py \
  | tee /tmp/b-family-untouched-historical-pilot-v21.txt

Paste the complete output back.

Important:
- No B logic changes.
- No exit testing.
- No runner-classifier testing.
- No tuning.
