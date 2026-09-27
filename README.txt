B FAMILY — RISK MODEL COMPARISON V8.1

Fixes the V8 reporting KeyError:
  exit_before_level -> exit_before_<30|50|75|100>

Also reports ambiguous rows separately instead of counting them as preserved.

Run:
cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/b_family_risk_model_comparison_v8_1.py \
  | tee /tmp/b-family-risk-model-comparison-v8-1.txt

Research only. No strategy/runtime changes.
