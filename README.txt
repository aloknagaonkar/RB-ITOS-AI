B FAMILY — V48 FROZEN POST-CAP20 RE-ENTRY VALIDATION

Frozen rule derived from V47:
After CAP20 rescue, allow ONE re-entry only when:
- within 20 minutes,
- close retakes degraded target,
- directional futures-VWAP is above rescue-time level.

Re-entry at 1m close.
Second leg exits only at original structural/session terminal.
No second rescue / no repeated re-entry.

Validation:
43 RUNNER_STRENGTHENING events from V40.1.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_post_cap20_reentry_validation_v48.py \
  | tee /tmp/b-family-post-cap20-reentry-validation-v48.txt

Paste the complete output back.
