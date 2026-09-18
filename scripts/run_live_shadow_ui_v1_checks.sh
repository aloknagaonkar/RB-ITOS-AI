#!/usr/bin/env bash
set -euo pipefail
cd ~/RB-ITOS-AI
source .venv/bin/activate

python scripts/apply_live_shadow_ui_v1.py
python -m pytest tests/test_live_shadow_ui_v1.py -v

cd frontend
npm run build

echo
echo "LIVE_SHADOW_UI_V1 backend tests and frontend build passed."
echo "Restart the FastAPI backend, then open the Live shadow tab."
