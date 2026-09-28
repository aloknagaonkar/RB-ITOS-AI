B FAMILY — V38 PROFIT-AWARE SELECTIVE RESCUE OPTIMIZATION
============================================================

V37 improved total points by only +13.20 versus V35, but reduced runner chase:
- +75: 92.3% -> 69.2%
- +100: 90.0% -> 60.0%

V38 keeps:
- V35_W1_AGE10 primary exit
- V37 RB1/G10 post-recovery rebreak rescue

But adds a causal rescue gate:
- only rescue if current captured directional points are <= cap

Caps tested:
0 / 10 / 20 / 30 / 40 / 50 / 75 points

Goal:
improve total points versus V35 while restoring as much +75/+100 chase as possible.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_profit_aware_selective_rescue_v38.py \
  | tee /tmp/b-family-profit-aware-selective-rescue-v38.txt

Paste the complete output back.
