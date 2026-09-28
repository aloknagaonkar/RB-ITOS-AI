B FAMILY — V49 OLDER 100-SESSION FROZEN RE-ENTRY VALIDATION

Frozen candidate:
PRIMARY_OFF + CAP20
+ one post-rescue re-entry within 20m when:
  - 1m close retakes degraded target
  - directional futures-VWAP > rescue-time level

The script automatically picks the most recent 100 dual-valid sessions
strictly before 2024-08-16.

No tuning.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_older_frozen_reentry_validation_v49.py \
  | tee /tmp/b-family-older-frozen-reentry-validation-v49.txt

Paste the complete output back.
