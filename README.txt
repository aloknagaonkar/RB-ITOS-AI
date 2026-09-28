B FAMILY — V30 POST-V29 RECOVERY PATH DIAGNOSTIC
==================================================

Purpose
-------
Study why 6/7 frozen V29 OOS exits were false exits.

For every V29-triggered runner, measure after the V29 exit:
- time to next new MFE
- further adverse excursion before that recovery
- directional futures-VWAP recovery
- time to VWAP recovery
- price retake of the V29 episode-start level
- time to price retake
- additional joint-deterioration episodes before next new MFE

V29 remains REJECTED.
V30 is descriptive only.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_post_v29_recovery_path_diagnostic_v30.py \
  | tee /tmp/b-family-post-v29-recovery-v30.txt

Paste the complete V30 output back.
