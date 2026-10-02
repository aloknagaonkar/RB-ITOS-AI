#!/usr/bin/env bash
set -euo pipefail
cd ~/RB-ITOS-AI
source .venv/bin/activate

python scripts/apply_live_shadow_step_audit_v1.py

python -m pytest \
  tests/test_live_shadow_step_audit_v1.py \
  tests/test_live_shadow_ui_v1.py \
  tests/test_live_shadow_production_wiring_v1.py \
  tests/test_full_shadow_integration_replay_v1.py -v

cd frontend
npm run build

echo
echo "LIVE_SHADOW_STEP_AUDIT_V1 checks passed."
echo "Restart with: ./scripts/restart.sh"
