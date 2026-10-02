#!/usr/bin/env bash
set -euo pipefail
REPO="${1:-$HOME/RB-ITOS-AI}"
cp backend/market_lab/candle_by_candle_validation_v1.py "$REPO/backend/market_lab/"
cp tests/test_candle_by_candle_validation_v1.py "$REPO/tests/"
mkdir -p "$REPO/docs/research"
cp docs/research/CANDLE_BY_CANDLE_VALIDATION_V1.md "$REPO/docs/research/"
echo "Applied CANDLE_BY_CANDLE_VALIDATION_V1 to $REPO"
