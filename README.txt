B FAMILY — V50 RECENT FROZEN RE-ENTRY VALIDATION

Range:
2026-09-09 through 2026-09-24

Frozen candidate:
PRIMARY_OFF + CAP20 + one 20-minute VWAP-confirmed re-entry.

No tuning.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_recent_frozen_reentry_validation_v50.py \
  | tee /tmp/b-family-recent-frozen-reentry-validation-v50.txt

Paste the complete output back.
