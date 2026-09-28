B FAMILY — V27 RUNNER PERSISTENCE / RECOVERY DIAGNOSTIC
=========================================================

Purpose
-------
Study whether runner deterioration is temporary or persistent.

V27 uses the existing V26 minute timeline and measures:
- longest consecutive VWAP weakening run
- longest consecutive no-new-MFE run
- longest consecutive joint deterioration run
- joint deterioration episode count
- which episodes later recover to a new MFE
- time from episode end to new MFE
- properties of the terminal deterioration episode

Joint deterioration remains sign-only:
  drawdown_from_running_mfe_close > 0
  AND
  vwap_change_vs_prior_minute < 0

No magnitude threshold is introduced.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_runner_persistence_recovery_diagnostic_v27.py \
  | tee /tmp/b-family-runner-persistence-recovery-v27.txt

Paste the complete output back.
