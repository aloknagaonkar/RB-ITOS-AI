#!/usr/bin/env bash
set -euo pipefail

cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_live_observational_shadow_v1.py \
  tests/test_live_observational_shadow_runtime_adapter_v1.py \
  tests/test_live_observational_data_health_v1.py \
  tests/test_live_normalized_feature_producer_v1.py \
  tests/test_live_nifty_futures_oi_producer_v1.py \
  tests/test_live_option_minute_source_v1.py -v

echo
echo "Live futures + option minute source checks passed."
echo "Next: FULL_SHADOW_INTEGRATION_REPLAY_V1."
