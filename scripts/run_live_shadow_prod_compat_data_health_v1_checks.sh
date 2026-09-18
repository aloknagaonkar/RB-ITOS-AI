#!/usr/bin/env bash
set -euo pipefail

cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_live_observational_shadow_v1.py \
  tests/test_live_observational_shadow_runtime_adapter_v1.py \
  tests/test_live_observational_data_health_v1.py -v

echo
echo "Production compatibility + data health checks passed."
echo "Next step: identify/build live normalized ALL3/futures/ATM/option-minute producer."
