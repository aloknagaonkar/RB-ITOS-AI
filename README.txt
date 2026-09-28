MIDPOINT M3.1 — FastAPI Query Default Fix

Cause:
FastAPI Query(...) objects are normally resolved by HTTP request injection.
The M3 smoke calls endpoint functions directly, so ui.events() received a
Query object instead of integer 200, causing:

TypeError: '<' not supported between instances of 'Query' and 'int'

Fix:
Use Annotated[int, Query(...)] with a normal integer Python default.

Run:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/apply_midpoint_m3_1_query_default_fix.py

python scripts/midpoint_m3_smoke.py

python -m pytest \
  tests/test_midpoint_m3_live_shadow_ui.py \
  tests/test_midpoint_m3_1_query_defaults.py -v

Only after these pass continue with:

python scripts/apply_midpoint_m3_workspace.py
