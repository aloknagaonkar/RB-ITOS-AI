B FAMILY — V37 POST-RECOVERY FAILURE / REBREAK OPTIMIZATION
==============================================================

V36 result:
- no improvement over V35
- simple degraded timeout is rejected as the next rescue mechanism

V37 keeps V35_W1_AGE10 as the fixed primary exit.

It studies V35 fallback events that:
1. recover by retaking the V32 recovery target
2. later lose that same target again

Search grid:
- rebreak persistence: 1 / 2 / 3 consecutive closes
- grace after recovery: 0 / 3 / 5 / 10 minutes
- confirmation:
    NONE
    VWAP_WEAK_VS_RECOVERY

Reports:
- total point improvement vs V35
- total point improvement vs V29
- total point difference vs V34.2 baseline
- mean / median / worst / best / max drawdown
- +30/+40/+50/+75/+100 chase rates
- later-new-MFE
- primary/rescue/fallback counts

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_post_recovery_rebreak_v37.py \
  | tee /tmp/b-family-post-recovery-rebreak-v37.txt

Paste the complete output back.
