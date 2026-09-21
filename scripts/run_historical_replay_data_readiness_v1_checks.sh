#!/usr/bin/env bash
set -euo pipefail
cd ~/RB-ITOS-AI
source .venv/bin/activate

python scripts/apply_historical_replay_data_readiness_v1.py

python -m py_compile   backend/market_lab/historical_replay_data_v1.py   backend/market_lab/historical_replay_data_api_v1.py   backend/market_lab/api.py

python -m pytest tests/test_historical_replay_data_v1.py -v

echo
python -m market_lab.historical_replay_data_v1 --date 2026-09-18 check
