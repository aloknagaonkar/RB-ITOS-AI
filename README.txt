MIDPOINT STRATEGY — M3B SHARED RUNTIME

Prerequisites: M1/M2/M3A passed.

Run in this order:

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

1) Coordinator smoke — fake source only, no broker call:

python scripts/midpoint_m3b_smoke.py

2) Tests:

python -m pytest \
  tests/test_midpoint_m3b_live_shadow_v1.py \
  tests/test_midpoint_m2_auditable_runtime.py \
  tests/test_midpoint_m3_live_shadow_ui.py \
  tests/test_midpoint_m3_1_query_defaults.py -v

3) Shared-source/worker patch DRY RUN:

python scripts/apply_midpoint_m3b_shared_source_worker.py

Expected:
source changed=True
worker changed=True
MIDPOINT_SHADOW_ENABLED default=0
DRY RUN ONLY

4) If clean, apply:

python scripts/apply_midpoint_m3b_shared_source_worker.py --apply

5) Re-run tests and imports:

python -m pytest \
  tests/test_midpoint_m3b_live_shadow_v1.py \
  tests/test_midpoint_m2_auditable_runtime.py \
  tests/test_midpoint_m3_live_shadow_ui.py \
  tests/test_midpoint_m3_1_query_defaults.py -v

python - <<'PY'
from market_lab.upstox_live_shadow_sources_v1 import UpstoxLiveShadowSourcesV1
from market_lab.midpoint_strategy.live_shadow_v1 import MidpointLiveShadowCoordinatorV1
from market_lab import live_shadow_worker_v1

assert hasattr(UpstoxLiveShadowSourcesV1, "nifty_futures_intraday_1m")
print("PASS: shared futures 1m source method")
print("PASS: Midpoint coordinator import")
print("PASS: worker import")
PY

IMPORTANT:
DO NOT set MIDPOINT_SHADOW_ENABLED=1 yet.
DO NOT restart the live worker yet.
DO NOT use pkill.
DO NOT use git add .

Backups created by patch are not for staging.

Suggested explicit staging after validation:

git add \
  backend/market_lab/midpoint_strategy/live_shadow_v1.py \
  backend/market_lab/upstox_live_shadow_sources_v1.py \
  backend/market_lab/live_shadow_worker_v1.py \
  scripts/apply_midpoint_m3b_shared_source_worker.py \
  scripts/midpoint_m3b_smoke.py \
  tests/test_midpoint_m3b_live_shadow_v1.py \
  docs/MIDPOINT_STRATEGY_M3B_SHARED_RUNTIME.md
