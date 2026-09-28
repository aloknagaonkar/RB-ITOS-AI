B FAMILY — V28 CAUSAL EPISODE CHECKPOINT DIAGNOSTIC
====================================================

Purpose
-------
Compare recovered vs non-recovered deterioration episodes at fixed causal
checkpoints:

- episode start
- +1 minute
- +3 minutes
- +5 minutes

Features:
- drawdown / running MFE
- drawdown points
- directional futures-VWAP diff
- cumulative VWAP change from episode start
- price recovery from worst directional close since episode start
- whether joint deterioration is still active

This is descriptive only.

No threshold search.
No exit rule.
No Family-B change.
No V20 change.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_causal_episode_checkpoint_diagnostic_v28.py \
  | tee /tmp/b-family-causal-episode-checkpoint-v28.txt

Paste the complete V28 output back.
