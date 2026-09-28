MIDPOINT STRATEGY — M3A WORKSPACE / API / UI

Prerequisites:
- M1 passed
- M2 passed

Copy package into repo preserving paths.

1. Backend/API projection smoke

cd ~/RB-ITOS-AI
source .venv/bin/activate
export PYTHONPATH=backend

python scripts/midpoint_m3_smoke.py

2. Tests

python -m pytest tests/test_midpoint_m3_live_shadow_ui.py -v

3. Dry-run existing-file patch

python scripts/apply_midpoint_m3_workspace.py

Expected:
DRY RUN ONLY

4. Apply only after dry-run succeeds

python scripts/apply_midpoint_m3_workspace.py --apply

5. Backend syntax / route test

python -m pytest tests/test_midpoint_m3_live_shadow_ui.py -v

6. Frontend build

cd frontend
npm run build
cd ..

7. Read-only shared-runtime preflight for M3B

python scripts/midpoint_m3_runtime_preflight.py \
  | tee /tmp/midpoint-m3-runtime-preflight.txt

Paste:
- M3 smoke output
- pytest output
- patch dry-run/apply output
- frontend build output
- runtime preflight output

Do NOT restart the live worker yet.
Do NOT run broad pkill commands.
Do NOT use git add .

Suggested explicit staging after all checks pass:

git add \
  backend/market_lab/midpoint_strategy/live_shadow_ui.py \
  frontend/src/midpointStrategyShadow.tsx \
  backend/market_lab/api.py \
  frontend/src/App.tsx \
  scripts/apply_midpoint_m3_workspace.py \
  scripts/midpoint_m3_smoke.py \
  scripts/midpoint_m3_runtime_preflight.py \
  tests/test_midpoint_m3_live_shadow_ui.py \
  docs/MIDPOINT_STRATEGY_M3_WORKSPACE_API_UI.md
