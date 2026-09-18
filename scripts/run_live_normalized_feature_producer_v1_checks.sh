#!/usr/bin/env bash
set -euo pipefail

cd ~/RB-ITOS-AI
source .venv/bin/activate

python -m pytest \
  tests/test_live_observational_shadow_v1.py \
  tests/test_live_observational_shadow_runtime_adapter_v1.py \
  tests/test_live_observational_data_health_v1.py \
  tests/test_live_normalized_feature_producer_v1.py -v

echo
echo "LIVE_NORMALIZED_FEATURE_PRODUCER_V1 checks passed."
echo "Next dependency: live NIFTY futures OI stream + exact option 1m candle source."
