#!/usr/bin/env bash
set -euo pipefail
cd ~/RB-ITOS-AI
source .venv/bin/activate
python -m pytest tests/test_live_observational_shadow_v1.py -v
mkdir -p data/live-observation/shadow-v1
EVENTS=data/live-observation/shadow-v1/events.jsonl
if [[ -f "$EVENTS" ]]; then
  python -m market_lab.live_observational_shadow_v1_cli verify --events "$EVENTS"
else
  echo "Core installed. No live shadow events yet; runtime adapter integration is the next step."
fi
