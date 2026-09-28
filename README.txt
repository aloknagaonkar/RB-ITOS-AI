B FAMILY — V28.1 CAUSAL EPISODE ROBUSTNESS / CORRECTION
=========================================================

Purpose
-------
Correct V28 same-episode persistence interpretation and add robustness checks.

Adds:
- correct SAME_EPISODE_ACTIVE accounting
- runner-level equal-weight comparison
- leave-one-runner-out stability

No threshold search.
No exit rule.
No Family-B change.
No V20 change.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_causal_episode_robustness_v28_1.py \
  | tee /tmp/b-family-causal-episode-robustness-v28_1.txt

Paste the full output back.
