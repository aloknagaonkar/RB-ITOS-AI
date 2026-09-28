B FAMILY — V47 POST-CAP20 RECOVERY / RE-ENTRY DIAGNOSTIC

Purpose:
Study what happens after the five CAP20 rescue exits from V43/V44/V45.

No tuning.
No rule changes.
No re-entry rule yet.

Measures:
- retake of degraded target
- rescue-price retake
- VWAP recovery
- +1/+3/+5/+10 minute checkpoints
- time to next new MFE
- post-rescue adverse excursion
- three descriptive causal re-entry markers

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_post_cap20_reentry_diagnostic_v47.py \
  | tee /tmp/b-family-post-cap20-reentry-diagnostic-v47.txt

Paste the complete output back.
