MIDPOINT M3B.1 FIX2

This replaces the failed first M3B.1 patch with anchors taken from the exact
current repo code shown by inspection.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/apply_midpoint_m3b_1_fix2.py

Expected all four:
changed=True

Then:
python scripts/apply_midpoint_m3b_1_fix2.py --apply

Then:
python -m pytest \
  tests/test_midpoint_m3b_1_fix2.py \
  tests/test_midpoint_m3b_live_shadow_v1.py \
  tests/test_midpoint_m2_auditable_runtime.py \
  tests/test_midpoint_m3_live_shadow_ui.py \
  tests/test_midpoint_m3_1_query_defaults.py -v

Then:
python scripts/midpoint_m3b_smoke.py

Keep MIDPOINT_SHADOW_ENABLED=0.
Do not restart worker.
Do not use git add .
